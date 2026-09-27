# create-pywire-app

Create a new [pywire](https://pywire.dev) app from npm:

```sh
npx create-pywire-app
# or
npm create pywire-app
```

pywire is a Python framework, so this package is a thin launcher: it runs the
[`create-pywire-app`](https://pypi.org/project/create-pywire-app/) wizard from PyPI
through [uv](https://docs.astral.sh/uv/), and installs uv first if it's missing.
Arguments pass straight through, e.g. `npx create-pywire-app my-app --yes --template blog`.

Already have uv? `uvx create-pywire-app` does the same thing without Node.js.
No uv and no Node.js? `curl -fsSL https://pywire.dev/install.sh | sh`.

See the [quickstart](https://pywire.dev/docs/guides/quickstart/) for what comes next.
