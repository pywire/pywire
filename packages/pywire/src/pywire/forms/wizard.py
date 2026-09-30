"""Multi-step forms: ``wizard(Model)`` fills a model one sub-model at a time.

    class Account(BaseModel):
        email: EmailStr

    class About(BaseModel):
        name: str

    class Signup(BaseModel):
        account: Account
        about: About

    signup = wizard(Signup)

    <form $bind={signup} @submit={create}>
      <input $if={signup.step == "account"} $bind={signup.account.email}>
      <input $if={signup.step == "about"} $bind={signup.about.name}>
      <button $if={not signup.on_first_step} {**signup.back_button}>Back</button>
      <button type="submit">{"Create" if signup.on_last_step else "Next"}</button>
    </form>

Each step's submit validates that step and moves on. The last one validates
the whole model and calls the handler with it, so rules across steps apply
there; an error on an earlier step's field goes back to that step.

What earlier steps held travels with the form in a hidden input, encrypted
and signed so it can't be read or changed (``PyWire(secret_key=...)`` shares
the key between processes). Secret fields (``SecretStr``, passwords) are
never carried even so: they must be on the last step, and ``wizard()``
refuses a model that puts one earlier. Files picked on earlier steps travel
as staged upload ids.
"""

from __future__ import annotations

import inspect
import re
from typing import Any, Callable, Dict, List, Literal, Mapping, Optional, Tuple

from pywire.forms.form import (
    MAX_ROWS,
    STATE,
    BoundField,
    Form,
    M,
    _action_button,
    _event_value,
    _is_secret,
    _mark_invalid,
    _pop_action,
    _takes_arg,
)
from pywire.forms.form import _secret as _secret  # the key wizard state is signed with
from pywire.forms.schema import FieldSpec
from pywire.forms.shape import Flat, normalize, shape
from pywire.runtime.uploads import PREFIX, Upload, resolve_uploads, staging_for

__all__ = ["STATE", "Wizard", "wizard"]

_UPLOAD_ID = re.compile(r"[0-9a-f]{8,12}-[0-9a-f]{32}")


def _secret_in(spec: FieldSpec, depth: int = 0) -> Optional[str]:
    """The dotted path of the first secret field under ``spec``, if any."""
    if depth > 8:
        return None
    for name, child in spec.children.items():
        if _is_secret(child):
            return name
        inner = child.item if child.kind == "list" else child
        found = _secret_in(inner, depth + 1) if inner is not None else None
        if found:
            return f"{name}.{found}"
    return None


def _staged_id(upload: Upload) -> Optional[str]:
    key = upload._key
    return key[len(PREFIX) :] if key.startswith(PREFIX) else None


class Wizard(Form[M]):
    """A form filled one step at a time. Create one with ``wizard(Model)``."""

    def __init__(self, model: type[M], **kwargs: Any) -> None:
        super().__init__(model, **kwargs)
        children = self._spec.children
        flat = [key for key, spec in children.items() if spec.kind != "model"]
        if not children or flat:
            raise TypeError(
                f"wizard() takes a model whose fields are its steps, each a "
                f"model: {model.__name__}.{flat[0] if flat else '?'} is not. "
                "Group the fields of each step in their own BaseModel."
            )
        self._steps: Tuple[str, ...] = tuple(children)
        for step in self._steps[:-1]:
            secret = _secret_in(children[step])
            if secret:
                raise TypeError(
                    f"wizard(): {model.__name__}.{step}.{secret} is a secret, and "
                    "secrets are never carried from one step to the next, so it "
                    "would be lost before the last step validates the model. Move "
                    f"it to the last step ({self._steps[-1]})."
                )
        self._index = 0
        # Staged upload ids of files picked on other steps, by HTML name.
        self._carried: Dict[str, List[str]] = {}

    # -- public state ------------------------------------------------------

    @property
    def step(self) -> str:
        """The current step: the name of its field on the model."""
        self._track()
        return self._steps[self._index]

    @property
    def steps(self) -> List[BoundField[Any]]:
        """Every step in order (``.label`` names it), e.g. for a progress bar."""
        return [self._field((key,)) for key in self._steps]

    @property
    def on_first_step(self) -> bool:
        self._track()
        return self._index == 0

    @property
    def on_last_step(self) -> bool:
        self._track()
        return self._index == len(self._steps) - 1

    @property
    def back_button(self) -> Dict[str, Any]:
        """Attributes for a button that goes back a step, keeping the input."""
        return _action_button("back")

    def reset(self) -> None:
        """Back to the first step and the initial values."""
        self._index = 0
        self._carried = {}
        super().reset()

    # -- snapshot hooks ----------------------------------------------------

    def __pw_snapshot__(self) -> Dict[str, Any]:
        return {**super().__pw_snapshot__(), **self._state()}

    def __pw_restore__(self, state: Mapping[str, Any]) -> None:
        super().__pw_restore__(state)
        if isinstance(state, Mapping):
            self._load(state)

    # -- the pipeline ------------------------------------------------------

    async def _pw_submit(self, page: Any, handler: Any, event: Any) -> None:
        form_data = _event_value(event, "formData")
        flat = normalize(form_data if isinstance(form_data, Mapping) else {})
        action = _pop_action(flat)
        carried = flat.pop(STATE, None)
        if carried and isinstance(carried[-1], str):
            self._restore_posted(carried[-1], page)

        step = self._steps[self._index]
        prefix = self._spec.children[step].data_key + "."
        # Only this step's rendered fields are read; read-only ones keep the
        # server's value.
        mine = {
            k: v for k, v in self._rendered_input(flat).items() if k.startswith(prefix)
        }
        earlier = {k: v for k, v in self._raw.items() if not k.startswith(prefix)}
        self._capture(mine)
        self._raw = {**earlier, **self._raw}
        self._carry_files(mine)

        if action == "back":
            self._move(self._index - 1)
            return
        if action is not None:
            self._apply_action(action)
            return

        merged = self._rendered_input({**self._raw, **await self._files(page), **mine})
        data = shape(self._spec, merged)
        self._keep_unrendered(self._spec, (), merged, data)
        if _event_value(event, "type") == "validate":
            self._validate_live(data, _event_value(event, "field"))
            self._keep_errors(step)
            return

        self._submitted = True
        instance = self._validate(data)
        if self._index < len(self._steps) - 1:
            self._keep_errors(step)
            self._value = None
            if self._errors:
                self._touch()
                _mark_invalid(page)
            else:
                self._move(self._index + 1)
            return
        if instance is None:
            earlier_step = next(
                (i for i, s in enumerate(self._steps) if self._has_errors(s)), None
            )
            if earlier_step is not None:
                self._index = earlier_step
            self._touch()
            _mark_invalid(page)
            return
        self._touch()
        if handler is not None:
            result = handler(instance) if _takes_arg(handler) else handler()
            if inspect.isawaitable(result):
                await result
        if self._errors:
            # An error the handler set on an earlier step's field shows there.
            here = self._steps[self._index]
            if not self._has_errors(here):
                self._index = next(
                    (i for i, s in enumerate(self._steps) if self._has_errors(s)),
                    self._index,
                )
                self._touch()
            _mark_invalid(page)

    # -- internals ---------------------------------------------------------

    def _state(self) -> Dict[str, Any]:
        return {
            **super()._state(),
            "step": self._index,
            "raw": {k: list(v) for k, v in self._raw.items()},
            "files": {k: list(v) for k, v in self._carried.items()},
        }

    def _restore_posted(self, blob: str, page: Any) -> bool:
        if not super()._restore_posted(blob, page):
            return False
        self._has_raw = True
        return True

    def _load(self, state: Mapping[str, Any]) -> None:
        super()._load(state)
        step = state.get("step")
        if isinstance(step, int) and 0 <= step < len(self._steps):
            self._index = step
        raw = state.get("raw")
        if isinstance(raw, Mapping):
            kept: Flat = {}
            for name, values in list(raw.items())[:MAX_ROWS]:
                _, spec = self._lookup(str(name))
                if spec is None or _is_secret(spec) or not isinstance(values, list):
                    continue
                kept[str(name)] = [v for v in values if isinstance(v, str)]
            self._raw = kept
        files = state.get("files")
        if isinstance(files, Mapping):
            self._carried = {
                str(name): [
                    i for i in ids if isinstance(i, str) and _UPLOAD_ID.fullmatch(i)
                ]
                for name, ids in files.items()
                if isinstance(ids, list) and self._lookup(str(name))[1] is not None
            }

    def _rows_removed(self, rename: Callable[[str], Optional[str]]) -> None:
        # Files picked on this step move with their rows too.
        self._carried = {
            new: ids for k, ids in self._carried.items() if (new := rename(k))
        }

    def _carry_files(self, mine: Flat) -> None:
        """Remember this step's files; a step shown again keeps its files."""
        for name, values in mine.items():
            ids = [i for v in values if isinstance(v, Upload) and (i := _staged_id(v))]
            if ids:
                self._carried[name] = ids

    async def _files(self, page: Any) -> Dict[str, List[Any]]:
        if not self._carried:
            return {}
        refs = {
            name: [{"_upload_id": i} for i in ids]
            for name, ids in self._carried.items()
        }
        # The ids come from state this server signed.
        resolved = await resolve_uploads(staging_for(page), refs, trusted=True)
        return {name: list(files) for name, files in resolved.items()}

    def _move(self, index: int) -> None:
        self._index = max(0, min(index, len(self._steps) - 1))
        self._errors = {}
        self._touched = set()
        self._submitted = False
        self._value = None
        self._touch()

    def _has_errors(self, step: str) -> bool:
        return any(k == step or k.startswith(step + ".") for k in self._errors)

    def _keep_errors(self, step: str) -> None:
        self._errors = {
            k: v
            for k, v in self._errors.items()
            if k == step or k.startswith(step + ".")
        }


def wizard(
    model: type[M],
    /,
    *,
    initial: Any = None,
    context: Any = None,
    messages: Any = None,
    id: Optional[str] = None,
    validate: Literal["blur", "submit"] = "blur",
) -> Wizard[M]:
    """Bind a model whose fields are steps (each a model) to a multi-step form.

    Takes the same options as :func:`pywire.forms.form`.
    """
    return Wizard(
        model,
        initial=initial,
        context=context,
        messages=messages,
        id=id,
        validate=validate,
    )
