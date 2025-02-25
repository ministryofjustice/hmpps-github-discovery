# HMPPS Github Discovery

## Github Discovery 

The `github_discovery.py` Python app queries the github api for information about hmpps projects and pushes that information into the **Components** collection of the HMPPS service catalogue.

It also updates elements of the **Products** collection in the HMPPS service catalogue.

A single component can be processed using `github_component_discovery.py` using the Service Catalogue component name as a parameter.

The `-f` or `--force-update` option will bypass checking to see if the environment has updated or the main branch will change, and will update all components.

The script and its suite of associated functions does the following:

### Components
- Retrieves a list of all components (microservices) from the service catalogue
- For each component, which has a github repository, it fetches key information (see below) via Github API
- If the environment configuration or main branch SHA has changed since the last scan it retrieves data from Helm and other files within the repository 
- It then updates each component in the service catalogue with the latest data from github.

### Products
- Retrieves a list of all products from the service catalogue
- For each product which has a valid (and non-private) Slack channel ID, it fetches the Slack channel name and updates that field in the service catalogue

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

Optional environment variables
- SLACK_NOTIFY_CHANNEL: Slack channel for notifications
- SLACK_ALERT_CHANNEL: Slack channel for alerts
- LOG_LEVEL: Log level (default: INFO)

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

## Classes, processes and functions

### Classes

- **AlertManager** (`classes/alertmanager.py`) contains a simple self-contained script that collects and parses data from the Alertmanager Status endpoint
- **CircleCI** (`classes/circleci.py`) contains functions that collect data either from the CircleCI configuration or from endpoints referred to by it
- **GithubSession** (`classes/github.py`) contains custom functions for the discovery script to read and process data from the Github organisation's repositories. It's built on PyGithub
- **HealthServer** (`classes/health.py`) is not used any more - it starts a simple HTTP server that responds to health pings. It's redundant now discovery is running as a crontab
- **ServiceCatalogue** (`classes/service_catalogue.py`) contains functions to read from and write to the Service Catalogue.
- **Slack** (`classes/slack.py`) contains functions to send Slack messages

### Processes

- **Components** (`processes\components.py`) deals with the main multithreaded processing of components. It's split into four main sections:
  - the dispatcher (`batch_process_sc_components`) which creates the threads, 
  - the processor (`process_sc_component`) which initiates processing of each component
  - independent elements (`process_independent_component`) which is carried out for each component
  - changed elements (`process_changed_component`) which - if environments have changed or the main branch has been updated since tht last run - reads configurations that may have changed within the repository

  Components also initiates the **Environments** (`includes/environments`) and **Helm Config** (`includes/helm.py`) functions, where details of those configurations are read and returned to the main functions

- **Products** (`processes/products.py`) deals with the multithread processing of product entries. Once again it's split into sections:
  - the dispatcher (`batch_process_sc_products`) which creates the threads
  - the processor (`process_sc_product`) which updates the data


### Includes

- **Utils** contains re-usable functions that are used across various processes
- **Helm** (`includes/helm.py`) reads and processes the helm configuration
- **Environments** (`includes/environments.py`) reads and processes other environment data, from either Bootstrap `projects.json` or Github Actions Environments.


## Github Teams Discovery

Github teams discovery (`github_team_discovery.py`) populates the **Github Teams** table of the Service Catalogue with team member data based on all the github teams associated with repositories. It checks against the [hmpps-github-teams](https://github.com/ministryofjustice/hmpps-github-teams/tree/main/terraform) terraform configuration and compiles a list of teams.

### Processes

- **Github Teams** (`processes\github_teams.py`) is the script that carries out the actual processing of the teams.

### Includes

- **Teams** (`includes/teams.py`) are functions to processes the teams either from Github or from Terraform data.


## Crontab

The Github Discovery and Github Teams Discovery scripts run on a Kubernetes cluster based on crontab settings within the [helm config](helm_deploy/values-prod.yaml).

Since the Service Catalogue database is copied from prod to dev every night at 11pm, there is no need to run Github Discovery in the dev environment.