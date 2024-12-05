# HMPPS Github Discovery

This Python app queries the github api for information about hmpps projects and pushes that information into the **Components** collection of the HMPPS service catalogue.

It also updates elements of the **Products** collection in the HMPPS service catalogue.


The app does the following:

### Components
- Retrieves a list of all components (microservices) from the service catalogue.
- For each component, which has a github repository, it fetches key information (see below) via github api.
- It then updates each component in the service catalogue with the latest data from github.

### Products
- Retrieves a list of all products from the service catalogue.
- For each product which has a valid (and non-private) Slack channel ID, it fetches the Slack channel name and updates that field in the service catalogue.


## Key information retrieved

This includes:
 - repository teams access (admin/maintain/write)
 - repository branch protection
 - repository language
 - repository visibility
 - repository topics

Retrieval of key data from files (if they exist):
 - `.circleci/config.yml` - hmpps orb version
 - `helm_deploy/` - various data including dependency chart versions.
 - `applicationinsights.json` - for azure app insights cloudRole_name
 - `package.json` - for azure app insights cloudRole_name

Retrieval of data from Alertmanager endpoint:

## Requirements
The following secrets are required:
 - **`GITHUB_APP_ID`** / **`GITHUB_APP_INSTALLATION_ID`** / **`GITHUB_APP_PRIVATE_KEY`** - Github keys
 - **`CIRCLECI_API_ENDPOINT`** / **`CIRCLECI_TOKEN`** Circle CI token
 - **`SLACK_BOT_TOKEN`** - this uses the [`hmpps-sre-app`](https://api.slack.com/apps/A07BZTDHRNK/general) Slack app
 - **`SERVICE_CATALOGUE_API_ENDPOINT`** / **`SERVICE_CATALOGUE_API_KEY`** - Service Catalogue API token
 - **`SC_FILTER`** (eg. `&filters[name][$contains]=-`) - Service Catalogue filter - **required for dev**

### Port forward to redis hosted in Cloud-platform

This is useful to do so you can test changes with real alertmanager data containing slack channel information. 

Create a port forward pod:

```bash
kubectl \
  -n hmpps-portfolio-management-dev \
  run port-forward-pod-alertmanager \
  --image=ministryofjustice/port-forward \
  --port=6379 \
  --env="REMOTE_HOST=[Alertmanager host]" \
  --env="LOCAL_PORT=6547" \
  --env="REMOTE_PORT=8080"
```

Use kubectl to port-forward to it:

```bash
kubectl \
  -n hmpps-portfolio-management-dev \
  port-forward \
  port-forward-pod-alertmanager 6574:6574
```

Ensure following redis environment variables are set:

```bash
export ALERTMANAGER_ENDPOINT='http://localhost:6574/alertmanager/status'
```