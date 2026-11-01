# Feeder - Exhibition Import System

This folder contains spreadsheets that can be imported to auto-populate exhibitions with pieces and their attributes.

## Expected Format

The spreadsheet (ODS or Excel) should follow this structure:

```
                Image1.jpg      Image2.jpg      Image3.jpg
Attribute 1     Value1          Value2          Value3
Attribute 2     Value1_2        Value2_2        Value3_2
...
```

### Layout Details:
- **First Row (except first cell)**: Embedded images for each piece
- **First Column (except first cell)**: Attribute names (e.g., "Name", "Year", "Artist", "Description")
- **Data Grid [row ≥ 2, col ≥ 2]**: Piece attributes aligned with their images

### Rules:
- The filename (without extension) becomes the exhibition name
- First column must include a "Name" attribute (it will be auto-created if missing)
- All attribute values are stored and linked to each piece
- Images must be embedded in the spreadsheet file
- Each piece gets its own Wagtail page with both "On Site" and "User Device" presentation pages
- Images are automatically set as hero_image on the presentation pages

## Usage

```bash
python manage.py feeder_import /path/to/spreadsheet.ods
```

Or from within the Feeder folder:
```bash
python manage.py feeder_import Feeder/spreadsheet.ods
```

## Example

Given a file named `"Removal Storage.ods"` with structure:

```
                Image1.jpg      Image2.jpg
Name            Vase            Sculpture
Year            1800            1920
Artist          John Doe        Jane Smith
```

The command will:
1. Create Exhibition: "Removal Storage"
2. Add attributes: ["Name", "Year", "Artist"]
3. Create 2 Pieces:
   - Vase (Year: 1800, Artist: John Doe) with Image1
   - Sculpture (Year: 1920, Artist: Jane Smith) with Image2

## Conflict Handling

If an exhibition with the same name already exists, a counter is automatically appended:
- "Removal Storage" → already exists
- Created as: "Removal Storage 2"

## Troubleshooting

**"ezodf is not installed"**
```bash
pip install ezodf lxml
```

**"Pillow is not installed"**
```bash
pip install Pillow
```

## File Format Support

- ✓ ODS (OpenDocument Spreadsheet)
- Excel support (partial - requires openpyxl)

## Future Enhancements

- Watch folder for automatic import
- Custom image resolution/processing
- Bulk attribute assignment
- Exhibition preview before import
