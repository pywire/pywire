"""Model-first forms.

    signup = form(Signup)          # Form[Signup]

    <form $bind={signup} @submit={create}>
      <input $bind={signup.email}>
    </form>

The Pydantic model writes the HTML5 attributes and is the only thing the
server trusts. Requires Pydantic v2 (``pip install "pywire[forms]"``).
"""

from pywire.forms.errors import FieldError
from pywire.forms.form import BoundField, FieldList, Form, form
from pywire.forms.schema import Option
from pywire.forms.uploads import UploadField
from pywire.forms.wizard import Wizard, wizard
from pywire.runtime.uploads import Upload

__all__ = [
    "form",
    "Form",
    "wizard",
    "Wizard",
    "BoundField",
    "FieldList",
    "FieldError",
    "Option",
    "Upload",
    "UploadField",
]
