# Framework for remote experiments in education

## OUTDATED, WILL BE UPDATED SHORTLYS

**-----  Unstructured, will be polished gradually. -----**

### General

Install Python 3+.

Checkout the git repository into a directory. Create a python virtual environment (let's call it `free-env`):
```
virtualenv free-env
```

This will create a new directory `free-env`. Then, active the environment:
```
source free-env/Scripts/activate
```
or
```
free-env/Scripts/activate.bat
```

The environment activation should be apparent by seeing `(free-env)` as a prefix of the command line. **From now on, all commands are assumed to be executed within the virtual environment**.

Install python's dependent packages:
```
pip install -r REQUIREMENTS.txt
```



### Database configuration

*TODO: Configure DB*

There is an example sqlite database included in the repository. No additional config needed to use it.

If using SQLite as database, enable JSONField extension as described here: https://code.djangoproject.com/wiki/JSON1Extension

**ONLY FOR NON-SQLITE DATABASES**

After the database is configured, we need to initialize it:
```
python manage.py migrate
```

Create a superuser for administrative access:
```
python manage.py createsuperuser
```

### Configuration

The application is configured with environment variables stored in the deployment environment in the `.env` file. Template for this file is in the `deploy\` directory. Fill in the individual configuration items, rename the file to `.env` and place it into the `freeweb\` directory.

### Compilation of CSS & JavaScript bundles

Install Node.js (https://nodejs.org/en/) and Yarn (https://yarnpkg.com/getting-started/install)
Navigate into `free/assets` folder and run:
```
yarn install
```

This should download all javascript dependencies for the project.

Manually download Semantic UI theme files from https://github.com/Semantic-Org/Semantic-UI-LESS and place them into the `free/assets/semantic-ui/themes` folder. Due to their size, they are not included in the repository.

Now you need to compile and package the theme and javascript files into bundles, so that the django website is able to use them. For this, you have three options what to execute in the `free/assets` folder:

- `yarn run build` - one-time dev build. Useful for running in the local environment, as the source codes are not obfuscated and minified.
- `yarn run watch` - continuous build. Used for javascript development, will automatically repackage the bundled files whenever source files are saved.
- `yarn run buildprod` - **PRODUCTION BUILD** - Use this if you want to publish the website to the external world. The source files will be obfuscated, minified, optimised for size etc.

### Development run

After all this, you can run the django development webserver with:
```
python manage.py runserver
```

In the production environment, the application should be bound to a production webserver using the WSGI interface.

## Development guidelines

### Python development

When adding python library, please update the `REQUIREMENTS.txt` file by running:

```
pip freeze > REQUIREMENTS.txt
```

### Internationalisation

Configure available languages for translation by setting `LANGUAGES` constant in `root_files/settings.py`. The template is:
```
LANGUAGES = [
    ('en', _('English')),
    ('pt', _('Portugese')),
]
```

If you increase the set of available languages, make sure you provide translations for applications' strings.

After any changes were made to texts displayed in the application, regenerate translation files:
```
cd free
django-admin makemessages -a
```

To execute this command, you need to have gettext installed. See https://mlocati.github.io/articles/gettext-iconv-windows.html

In `free/locale/<lang_code>` you should be able to see `.po` files containing strings extracted from the source code. Translate those strings. After changes to `.po` files run compilation (also in `free` directory):
```
django-admin compilemessages
```

This will create `.mo` files that will be used for translating strings in-app.

*TODO: Javascript internationalisation*

### API

The API documentation is automatically generated on `/free-api.json`, `/free-api.yaml` (machine-readable formats),
or `/api/swagger` and `/api/redoc` (human-readable formats).

### Testing

Tests for the app should be located in the `free\tests` folder. You can run the tests using 
```
python manage.py test free
```

### Front-end development

To develop code of individual react components, place them as source files into the `free/assets/src/components` folder. All those files will be bundled into `common` bundle by webpack. 

It is recommended to use React hooks. To package a functional component for use in django templates, you need to prefix the function name with `/**/`. This is an annotation that the django loader system uses to distinguish internal functions and components. Class-based components should be recognised automatically. 