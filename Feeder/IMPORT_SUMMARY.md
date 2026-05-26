# Feeder Import Complete ✓

## Summary

Successfully imported the **Removal Storage** exhibition with **14 pieces** from the ODS spreadsheet.

### What Was Created

**Exhibition:** Removal Storage
- 7 attributes configured: Name, Date of Creation, Disk Capacity, Physical Size(cm), Launch Price($), Host Device, Owner
- 14 pieces imported with all attributes populated
- Each piece has a dedicated Wagtail page with "On Site" and "User Device" presentation sections

### Pieces Imported
1. IBM Diskette 1
2. FUJI FILM MD2D
3. Genius IBM Mouse Driver
4. Lotus 1-2-3 for Windows
5. iomega zip250
6. Bubble Memory Cartridge
7. BASF Computer Tape
8. HP Disk Pack
9. WANG Disk Pack
10. HP Certified Data Cartridge
11. IBM 80-column punched card
12. Orion – Sabre Wulf
13. iomega click!40
14. HP Top Load Disc Drive

### How It Works

The `feeder_import` management command:
1. **Reads the ODS file** - Parses the spreadsheet structure
2. **Extracts images** - Embeds the images from the first row into Wagtail's Image model
3. **Identifies attributes** - Gets attribute names from the first column
4. **Creates Exhibition** - Generates an ExhibitionPage with On Site and User Device sections
5. **Populates Pieces** - Creates each piece as a PiecePage with:
   - All attributes from the spreadsheet
   - Wagtail presentation pages (On Site & User Device)
   - Hero images from the spreadsheet
6. **Handles conflicts** - If an exhibition name exists, appends a counter (e.g., "Exhibition 2")

### Access Your Exhibition

- **Admin Edit:** http://127.0.0.1:8000/exhibition/1/update
- **Public On-Site Display:** http://127.0.0.1:8000/exhibition/1/presentation/on_site
- **User Device Display:** http://127.0.0.1:8000/exhibition/1/presentation/user_device

### Future Imports

To import another exhibition:
```bash
python manage.py feeder_import Feeder/YourFile.ods
```

The command will automatically:
- Detect the file name as the exhibition title
- Extract all images and attributes from the spreadsheet
- Create all pieces with their attributes and images
- Link images to the Wagtail presentation pages (same as admin workflow)

---

**Note:** Images are stored in Wagtail's Image model (same location as manually uploaded images). The command replaces manual admin work of:
- Creating exhibition
- Adding 7 attributes manually
- Creating 14 pieces one-by-one
- Uploading 14 images
- Linking images to presentation pages
