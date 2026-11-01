import os
import io
import zipfile
import re
from pathlib import Path
from django.core.management.base import BaseCommand, CommandError
from django.core.files.base import ContentFile
from django.db import transaction
from django.contrib.auth.models import User
from main_app.models import (
    Exhibition, Piece, ExhibitionPage, ExhibitionOnSitePage, 
    ExhibitionUserDevicePage, ExhibitionPiecesListPage, PiecePage, 
    PieceOnSitePage, PieceUserDevicePage
)
from main_app.views.models_views import (
    _unique_child_slug, _get_or_create_child_page, _save_as_draft
)
from wagtail.images.models import Image
from wagtail.models import Page

try:
    import ezodf
except ImportError:
    ezodf = None

try:
    from PIL import Image as PILImage
except ImportError:
    PILImage = None

try:
    import openpyxl
except ImportError:
    openpyxl = None


class Command(BaseCommand):
    help = 'Import an exhibition with pieces from an ODS/Excel file in the Feeder folder'

    def add_arguments(self, parser):
        parser.add_argument('file', type=str, nargs='?', default=None, 
                           help='Filename to import (optional - auto-detects if not specified)')

    def _find_file_in_feeder(self):
        """Auto-detect ODS/Excel files in Feeder folder."""
        feeder_dir = 'Feeder'
        
        if not os.path.isdir(feeder_dir):
            raise CommandError(f'Feeder directory not found at {feeder_dir}')
        
        # Find ODS and Excel files
        supported_extensions = ('.ods', '.xlsx', '.xls')
        files = [f for f in os.listdir(feeder_dir) 
                if os.path.isfile(os.path.join(feeder_dir, f)) 
                and f.lower().endswith(supported_extensions)
                and not f.startswith('.')]  # Skip hidden files
        
        if not files:
            raise CommandError(f'No ODS/Excel files found in {feeder_dir}')
        
        if len(files) > 1:
            self.stdout.write(f'Multiple files found in {feeder_dir}:')
            for i, f in enumerate(files, 1):
                self.stdout.write(f'  {i}. {f}')
            raise CommandError('Please specify which file to import')
        
        file_path = os.path.join(feeder_dir, files[0])
        self.stdout.write(f'Auto-detected file: {file_path}')
        return file_path

    def handle(self, *args, **options):
        file_arg = options['file']
        
        # If no file specified, auto-detect from Feeder folder
        if file_arg is None:
            file_path = self._find_file_in_feeder()
        else:
            # If file_arg is just a filename (no path separators), assume it's in the Feeder folder
            if os.sep not in file_arg and '/' not in file_arg:
                file_path = os.path.join('Feeder', file_arg)
            else:
                file_path = file_arg

        if not os.path.exists(file_path):
            raise CommandError(f'File not found: {file_path}')

        if ezodf is None:
            raise CommandError('ezodf is not installed. Run: pip install ezodf lxml')

        # Read the spreadsheet
        try:
            doc = ezodf.opendoc(file_path)
            sheet = doc.sheets[0]
            self.file_path = file_path  # Store for image extraction
        except Exception as e:
            raise CommandError(f'Error reading file: {e}')

        # Extract data
        self.stdout.write('Parsing spreadsheet...')
        images, attributes, pieces_data = self._parse_sheet(sheet)

        if not pieces_data:
            raise CommandError('No piece data found in spreadsheet')

        # Count actual pieces (skip empty ones)
        actual_pieces = sum(1 for data in pieces_data.values() 
                           if data['attributes'].get('name', '').strip())

        exhibition_name = Path(file_path).stem
        self.stdout.write(f'Exhibition name: {exhibition_name}')
        self.stdout.write(f'Found {len(attributes)} attributes and {actual_pieces} pieces')

        # Create exhibition with transaction
        try:
            with transaction.atomic():
                exhibition = self._create_exhibition(exhibition_name)
                self._add_attributes_to_exhibition(exhibition, attributes)
                self._create_pieces(exhibition, attributes, pieces_data, images)
                self.stdout.write(self.style.SUCCESS(
                    f'Successfully created exhibition "{exhibition.title}" with {actual_pieces} pieces'
                ))
        except Exception as e:
            raise CommandError(f'Error creating exhibition: {e}')

    def _parse_sheet(self, sheet):
        """Extract images, attributes, and piece data from sheet."""
        image_refs = {}
        attributes = []
        pieces_data = {}

        # Get max rows and columns using sheet dimensions
        max_row = sheet.nrows()
        max_col = sheet.ncols()

        if max_row < 2 or max_col < 2:
            raise CommandError('Spreadsheet must have at least 2 rows and 2 columns')

        # First row (index 0) contains images - skip header cell at [0,0]
        self.stdout.write('Extracting image references...')
        for col_idx in range(1, max_col):
            cell = sheet[(0, col_idx)]
            # Images in ezodf cells are typically stored as draw:image in the cell
            image_filename = self._get_image_filename_from_cell(cell)
            if image_filename:
                image_refs[col_idx] = image_filename
                self.stdout.write(f'  Found image reference: {image_filename}')

        # Extract actual image data from ODS archive
        self.stdout.write('Loading images from archive...')
        images = self._extract_images_from_ods(image_refs)

        # First column (index 0) contains attributes - skip header cell at [0,0]
        self.stdout.write('Extracting attributes...')
        for row_idx in range(1, max_row):
            cell = sheet[(row_idx, 0)]
            attr_name = self._get_cell_value(cell)
            if attr_name and attr_name.strip():
                attributes.append(attr_name.strip())
                self.stdout.write(f'  Found attribute: {attr_name}')

        # Piece data - cells [row >= 1, col >= 1]
        self.stdout.write('Extracting piece data...')
        for col_idx in range(1, max_col):
            piece_values = {}
            for row_idx, attr_name in enumerate(attributes, start=1):
                cell = sheet[(row_idx, col_idx)]
                value = self._get_cell_value(cell)
                piece_values[attr_name.lower()] = value if value else ''
            
            pieces_data[col_idx] = {
                'attributes': piece_values,
                'image_col': col_idx,
            }

        return images, attributes, pieces_data

    def _get_cell_value(self, cell):
        """Extract string value from a cell."""
        if cell is None:
            return None
        try:
            return str(cell.plaintext()).strip() if hasattr(cell, 'plaintext') else str(cell).strip()
        except:
            return None

    def _get_image_filename_from_cell(self, cell):
        """Extract image filename reference from a cell in ODS."""
        try:
            if hasattr(cell, 'node') and cell.node is not None:
                # Look for draw:image elements in the cell
                for child in cell.node:
                    if 'image' in child.tag.lower():
                        # Get the xlink:href attribute
                        href = child.get('{http://www.w3.org/1999/xlink}href')
                        if href:
                            return href
        except:
            pass
        return None

    def _extract_images_from_ods(self, image_refs):
        """Extract actual image data from ODS file using the image references."""
        images = {}
        try:
            with zipfile.ZipFile(self.file_path, 'r') as ods_zip:
                for col_idx, image_ref in image_refs.items():
                    if not image_ref:
                        continue
                    try:
                        # image_ref is typically "Pictures/Image1.jpg" or similar
                        image_data = ods_zip.read(image_ref)
                        images[col_idx] = image_data
                        self.stdout.write(f'  Extracted {image_ref}')
                    except KeyError:
                        self.stdout.write(f'  Warning: Could not find {image_ref} in archive')
        except Exception as e:
            self.stdout.write(f'Warning: Could not extract images: {e}')
        return images

    def _create_exhibition(self, name):
        """Create exhibition with conflict handling using proper helpers."""
        base_name = name
        exhibition_name = base_name
        counter = 1

        while Exhibition.objects.filter(title=exhibition_name).exists():
            counter += 1
            exhibition_name = f'{base_name} {counter}'

        exhibition = Exhibition.objects.create(
            title=exhibition_name,
            description='Auto-imported from feeder'
        )

        # Add first superuser as admin (so it shows up in their exhibitions list)
        admin_user = User.objects.filter(is_superuser=True).first()
        if admin_user:
            exhibition.admins.add(admin_user)
            self.stdout.write(f'  Added {admin_user.username} as admin')
        else:
            self.stdout.write('  Warning: No superuser found to assign as admin')

        # Create Wagtail ExhibitionPage hierarchy using proper helpers
        root = Page.get_first_root_node()
        exhibition_slug = _unique_child_slug(root, exhibition_name)
        
        # Clean up any existing pages with the same slug to avoid conflicts
        existing_exhibition_page = ExhibitionPage.objects.filter(
            slug=exhibition_slug,
            path__startswith=root.path
        ).first()
        if existing_exhibition_page:
            self.stdout.write(f'  Deleting existing page with slug "{exhibition_slug}"...')
            existing_exhibition_page.delete()
        
        exhibition_page = ExhibitionPage(
            title=exhibition_name,
            slug=exhibition_slug,
        )
        root.add_child(instance=exhibition_page)
        _save_as_draft(exhibition_page)

        # Create child pages using idempotent helper
        _get_or_create_child_page(
            exhibition_page,
            ExhibitionOnSitePage,
            title="On Site",
            slug="on_site",
        )
        _get_or_create_child_page(
            exhibition_page,
            ExhibitionUserDevicePage,
            title="User Device",
            slug="user_device",
        )
        _get_or_create_child_page(
            exhibition_page,
            ExhibitionPiecesListPage,
            title="Pieces",
            slug="pieces",
        )

        exhibition.slideshow_page = exhibition_page
        exhibition.save()

        self.stdout.write(f'Created exhibition: {exhibition.title}')
        return exhibition

    def _add_attributes_to_exhibition(self, exhibition, attributes):
        """Add attribute definitions to exhibition."""
        exhibition.pieces_attributes = attributes
        exhibition.save()
        self.stdout.write(f'Added {len(attributes)} attributes to exhibition')

    def _create_pieces(self, exhibition, attributes, pieces_data, images):
        """Create pieces with wagtail pages and images using proper helpers."""
        # Get the pieces list page
        pieces_list_page = exhibition.slideshow_page.get_children().filter(slug='pieces').first()
        if not pieces_list_page:
            raise CommandError('Could not find pieces list page')

        for col_idx, data in pieces_data.items():
            piece_attrs = data['attributes']
            piece_name = piece_attrs.get('name', '').strip()
            
            # Skip empty pieces
            if not piece_name:
                self.stdout.write(f'Skipping empty piece at column {col_idx}')
                continue

            self.stdout.write(f'Creating piece: {piece_name}')

            # Create Piece object
            piece = Piece.objects.create(
                exhibition=exhibition,
                attributes=[
                    {'name': attr, 'value': piece_attrs.get(attr.lower(), '')}
                    for attr in attributes
                ]
            )

            # Create Wagtail PiecePage using proper helpers
            piece_slug = _unique_child_slug(pieces_list_page, f"piece-{piece.pk}-{piece_name}")
            
            # Clean up any existing piece page with the same slug to avoid conflicts
            existing_piece_page = pieces_list_page.get_children().filter(
                slug=piece_slug
            ).first()
            if existing_piece_page:
                self.stdout.write(f'  Deleting existing piece page with slug "{piece_slug}"...')
                existing_piece_page.delete()
            
            piece_page = PiecePage(
                title=piece_name,
                slug=piece_slug,
            )
            pieces_list_page.add_child(instance=piece_page)
            _save_as_draft(piece_page)

            # Create child pages using idempotent helper
            _get_or_create_child_page(
                piece_page,
                PieceOnSitePage,
                title="On Site",
                slug="on_site",
            )
            _get_or_create_child_page(
                piece_page,
                PieceUserDevicePage,
                title="User Device",
                slug="user_device",
            )

            # Add image if available
            if col_idx in images:
                image_data = images[col_idx]
                if image_data:
                    wagtail_image = self._save_image_to_wagtail(piece_name, image_data)
                    if wagtail_image:
                        on_site_page = piece_page.get_children().filter(slug='on_site').first()
                        user_device_page = piece_page.get_children().filter(slug='user_device').first()
                        if on_site_page:
                            on_site_page = on_site_page.specific
                            on_site_page.hero_image = wagtail_image
                            on_site_page.save()
                        if user_device_page:
                            user_device_page = user_device_page.specific
                            user_device_page.hero_image = wagtail_image
                            user_device_page.save()

            piece.slideshow_page = piece_page
            piece.save()

            self.stdout.write(f'  ✓ Created piece: {piece_name}')

    def _save_image_to_wagtail(self, name, image_data):
        """Save image data to Wagtail Image model."""
        if not image_data:
            return None

        try:
            # Determine file extension from image data
            extension = self._get_image_extension(image_data)
            if not extension:
                extension = 'jpg'

            # Create a Wagtail Image object
            wagtail_image = Image.objects.create(
                title=name,
                file=ContentFile(image_data, name=f'{self._slugify(name)}.{extension}')
            )
            self.stdout.write(f'    ✓ Image saved: {name}')
            return wagtail_image
        except Exception as e:
            self.stdout.write(f'    Warning: Could not save image: {e}')
            return None

    def _get_image_extension(self, image_data):
        """Determine image format from file signature."""
        if image_data.startswith(b'\xff\xd8\xff'):
            return 'jpg'
        elif image_data.startswith(b'\x89PNG'):
            return 'png'
        elif image_data.startswith(b'GIF8'):
            return 'gif'
        elif image_data.startswith(b'RIFF') and b'WEBP' in image_data[:20]:
            return 'webp'
        return None

    def _slugify(self, name):
        """Simple slug generation."""
        import re
        slug = re.sub(r'[^\w\s-]', '', name.lower())
        slug = re.sub(r'[-\s]+', '-', slug)
        return slug.strip('-')
