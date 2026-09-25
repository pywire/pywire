---
title: Stateless provider quickstarts
description: Build and deploy PyWire stateless apps to Cloudflare, AWS, Azure, and Google Cloud.
---

Set `PyWire(stateless=True)` before building and provision `PYWIRE_SECRET_KEY` in the target environment. Generated deployment READMEs under `.pywire/deploy/<platform>/` are the authoritative provider-specific instructions; regenerate them rather than hand-editing them.

## Cloudflare edge Worker

This target uses Python Workers/Pyodide and a plain Worker—no Durable Object. It is stateless-only.

```sh
pywire build --platform cloudflare-edge
npx wrangler dev
npx wrangler deploy
```

Set `PYWIRE_SECRET_KEY` as a Wrangler secret; never commit it. For production, prefer the deployment's secret binding over a plain environment value. The real-worker gate measured an action p50 of about 2.65 ms, a 232 B counter snapshot, a 251 B 1000-row toggle, and about 79 ms Pyodide cold start. These are workerd measurements, not Cloudflare service promises.

## AWS Lambda

The template vendors dependencies into `package/`, targets x86_64 and Python 3.12, and runs native CPython. From the project root:

```sh
cp -R src .pywire/deploy/aws/src
cd .pywire/deploy/aws
zip -r function.zip handler.py _routes.py _pywire_build package src
```

For a root-level `main:app`, copy `main.py` instead and include it in place of `src`. Create an API Gateway HTTP API, Lambda integration, and catch-all route:

```sh
function_arn=$(aws lambda create-function --function-name YOUR_FUNCTION_NAME --runtime python3.12 --handler handler.handler --role arn:aws:iam::YOUR_ACCOUNT_ID:role/lambda-execution-role --zip-file fileb://function.zip --query FunctionArn --output text)
api_id=$(aws apigatewayv2 create-api --api-name YOUR_FUNCTION_NAME --protocol-type HTTP --query ApiId --output text)
integration_id=$(aws apigatewayv2 create-integration --api-id "$api_id" --integration-type AWS_PROXY --integration-uri "$function_arn" --query IntegrationId --output text)
aws apigatewayv2 create-route --api-id "$api_id" --route-key '$default' --target "integrations/$integration_id"
aws apigatewayv2 create-stage --api-id "$api_id" --stage-name '$default'
```

Generate and configure the signing secret without putting a literal in shell history:

```sh
export PYWIRE_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
aws lambda update-function-configuration --function-name YOUR_FUNCTION_NAME --environment "Variables={PYWIRE_SECRET_KEY=$PYWIRE_SECRET_KEY}"
```

## Azure Functions

The generated `.pywire/deploy/azure/` directory is the uploadable function package. From the project root:

```sh
cd .pywire/deploy/azure
python -m pip install -r requirements.txt
func start
```

`local.settings.json` ships with an empty `PYWIRE_SECRET_KEY`; PyWire refuses to boot until it is populated. Generate a value for local use:

```sh
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Before deployment, set a fresh `PYWIRE_SECRET_KEY` application setting in the portal or with `az functionapp config appsettings set`. Package and upload the **contents**, excluding local settings:

```sh
zip -r function.zip . -x local.settings.json -x function.zip -x '*__pycache__*'
func azure functionapp publish YOUR_FUNCTION_NAME --zip-path function.zip
```

This target runs native CPython.

## Google Cloud Run

Cloud Run is a long-running container and can host either tier. From the project root:

```sh
cp .pywire/deploy/gcp_cloudrun/Dockerfile ./Dockerfile
gcloud run deploy YOUR_PROJECT_NAME \
  --source . \
  --region us-central1
```

For stateless mode, provide the signing secret in the same deploy command:

```sh
gcloud run deploy YOUR_PROJECT_NAME \
  --source . \
  --region us-central1 \
  --set-env-vars PYWIRE_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

For production, store the value in Secret Manager and use `--set-secrets PYWIRE_SECRET_KEY=NAME:latest` instead. Add `--session-affinity` only for WebSocket/session-affinity mode.

## Google Cloud Functions

This target uses native CPython and uploads the generated directory as-is. Deploy from the project root:

```sh
gcloud functions deploy YOUR_PROJECT_NAME \
  --gen2 \
  --runtime=python312 \
  --region=us-central1 \
  --source=.pywire/deploy/gcp_functions \
  --entry-point=pywire \
  --trigger-http \
  --set-env-vars=PYWIRE_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')" \
  --allow-unauthenticated
```

**Entrypoint caveat:** functions-framework reserves `main.py` for its entrypoint. A root-level `main:app` application collides with that filename. Rename the application module or use the `src/` layout so the generated entrypoint remains `main.py`.
