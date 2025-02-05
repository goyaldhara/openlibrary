from __future__ import print_function

import sys
from typing import List

import web
import os
import shutil

import babel
from babel._compat import BytesIO
from babel.support import Translations
from babel.messages import Catalog
from babel.messages.pofile import read_po, write_po
from babel.messages.mofile import write_mo
from babel.messages.extract import extract_from_file, extract_from_dir, extract_python

root = os.path.dirname(__file__)

def _compile_translation(po, mo):
    try:
        catalog = read_po(open(po, 'rb'))

        f = open(mo, 'wb')
        write_mo(f, catalog)
        f.close()
        print('compiled', po, file=web.debug)
    except Exception as e:
        print('failed to compile', po, file=web.debug)
        raise e


def _validate_catalog(catalog, locale):
    validation_errors = []
    for message in catalog:
        if message.fuzzy:
            if message.lineno:
                validation_errors.append(
                    f'openlibrary/i18n/{locale}/messages.po:{message.lineno}:'
                    f' "{message.string}" is fuzzy.'
                )
            else:
                validation_errors.append(
                    '  File is fuzzy.  Remove line containing "#, fuzzy" found near '
                    'the beginning of the file.'
                )

    if validation_errors:
        print("Validation failed...")
        print("Please correct the following errors before proceeding:")
        for e in validation_errors:
            print(e)

    return len(validation_errors) == 0


def validate_translations(args):
    if args:
        locale = args[0]
        po_path = os.path.join(root, locale, 'messages.po')

        if os.path.exists(po_path):
            catalog = read_po(open(po_path, 'rb'))
            is_valid = _validate_catalog(catalog, locale)

            if is_valid:
                print(f'Translations for locale "{locale}" are valid!')
            return is_valid
        else:
            print(f'Portable object file for locale "{locale}" does not exist.')
            return False
    else:
        print('Must include locale code when executing validate.')
        return False


def get_locales():
    return [
        d
        for d in os.listdir(root)
        if (os.path.isdir(os.path.join(root, d)) and
            os.path.exists(os.path.join(root, d, 'messages.po')))
    ]

def extract_templetor(fileobj, keywords, comment_tags, options):
    """Extract i18n messages from web.py templates."""
    try:
        instring = fileobj.read().decode('utf-8')
        # Replace/remove inline js '\$' which interferes with the Babel python parser:
        cleaned_string = instring.replace('\$', '')
        code = web.template.Template.generate_code(cleaned_string, fileobj.name)
        f = BytesIO(code.encode('utf-8')) # Babel wants bytes, not strings
    except Exception as e:
        print('Failed to extract ' + fileobj.name + ':', repr(e), file=web.debug)
        return []
    return extract_python(f, keywords, comment_tags, options)


def extract_messages(dirs: List[str]):
    catalog = Catalog(
        project='Open Library',
        copyright_holder='Internet Archive'
    )
    METHODS = [
        ("**.py", "python"),
        ("**.html", "openlibrary.i18n:extract_templetor")
    ]
    COMMENT_TAGS = ["NOTE:"]

    for d in dirs:
        extracted = extract_from_dir(d, METHODS, comment_tags=COMMENT_TAGS,
                                     strip_comment_tags=True)

        counts = {}
        for filename, lineno, message, comments, context in extracted:
            counts[filename] = counts.get(filename, 0) + 1
            catalog.add(message, None, [(filename, lineno)], auto_comments=comments)

        for filename, count in counts.items():
            path = filename if d == filename else os.path.join(d, filename)
            print(f"{count}\t{path}", file=sys.stderr)

    path = os.path.join(root, 'messages.pot')
    f = open(path, 'wb')
    write_po(f, catalog)
    f.close()

    print('wrote template to', path)


def compile_translations(locales: List[str]):
    locales_to_update = locales or get_locales()

    for locale in locales_to_update:
        po_path = os.path.join(root, locale, 'messages.po')
        mo_path = os.path.join(root, locale, 'messages.mo')

        if os.path.exists(po_path):
            _compile_translation(po_path, mo_path)


def update_translations(locales: List[str]):
    locales_to_update = locales or get_locales()
    print(f"Updating {locales_to_update}")

    pot_path = os.path.join(root, 'messages.pot')
    template = read_po(open(pot_path, 'rb'))

    for locale in locales_to_update:
        po_path = os.path.join(root, locale, 'messages.po')
        mo_path = os.path.join(root, locale, 'messages.mo')

        if os.path.exists(po_path):
            catalog = read_po(open(po_path, 'rb'))
            catalog.update(template)

            f = open(po_path, 'wb')
            write_po(f, catalog)
            f.close()
            print('updated', po_path)
        else:
            print(f"ERROR: {po_path} does not exist...")

    compile_translations(locales_to_update)


def generate_po(args):
    if args:
        po_dir = os.path.join(root, args[0])
        pot_src = os.path.join(root, 'messages.pot')
        po_dest = os.path.join(po_dir, 'messages.po')

        if os.path.exists(po_dir):
            if os.path.exists(po_dest):
                print(f"Portable object file already exists at {po_dest}")
            else:
                shutil.copy(pot_src, po_dest)
                os.chmod(po_dest, 0o666)
                print(f"File created at {po_dest}")
        else:
            os.mkdir(po_dir)
            os.chmod(po_dir, 0o777)
            shutil.copy(pot_src, po_dest)
            os.chmod(po_dest, 0o666)
            print(f"File created at {po_dest}")
    else:
        print("Add failed. Missing required locale code.")


@web.memoize
def load_translations(lang):
    po = os.path.join(root, lang, 'messages.po')
    mo_path = os.path.join(root, lang, 'messages.mo')

    if os.path.exists(mo_path):
        return Translations(open(mo_path, 'rb'))

@web.memoize
def load_locale(lang):
    try:
        return babel.Locale(lang)
    except babel.UnknownLocaleError:
        pass

class GetText:
    def __call__(self, string, *args, **kwargs):
        """Translate a given string to the language of the current locale."""
        # Get the website locale from the global ctx.lang variable, set in i18n_loadhook
        translations = load_translations(web.ctx.lang)
        value = (translations and translations.ugettext(string)) or string

        if args:
            value = value % args
        elif kwargs:
            value = value % kwargs

        return value

    def __getattr__(self, key):
        from infogami.utils.i18n import strings
        # for backward-compatability
        return strings.get('', key)

class LazyGetText:
    def __call__(self, string, *args, **kwargs):
        """Translate a given string lazily."""
        return LazyObject(lambda: GetText()(string, *args, **kwargs))

class LazyObject:
    def __init__(self, creator):
        self._creator = creator

    def __str__(self):
        return web.safestr(self._creator())

    def __repr__(self):
        return repr(self._creator())

    def __add__(self, other):
        return self._creator() + other

    def __radd__(self, other):
        return other + self._creator()


def ungettext(s1, s2, _n, *a, **kw):
    # Get the website locale from the global ctx.lang variable, set in i18n_loadhook
    translations = load_translations(web.ctx.lang)
    value = translations and translations.ungettext(s1, s2, _n)
    if not value:
        # fallback when translation is not provided
        if _n == 1:
            value = s1
        else:
            value = s2

    if a:
        return value % a
    elif kw:
        return value % kw
    else:
        return value

def gettext_territory(code):
    """Returns the territory name in the current locale."""
    # Get the website locale from the global ctx.lang variable, set in i18n_loadhook
    locale = load_locale(web.ctx.lang)
    return locale.territories.get(code, code)

gettext = GetText()
ugettext = gettext
lgettext = LazyGetText()
_ = gettext
