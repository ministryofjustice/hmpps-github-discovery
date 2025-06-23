# HMPPS Github Discovery

## Overview

A suite of Python discovery apps that query Github for information about hmpps projects and pushes that information into the the HMPPS service catalogue.

This includes:
- **components** - (`github_discovery.py`) - Github repository parameters to update the Components collection within the Service Catalogue
- **products** - (also run as part of `github_discovery.py`) - processes and updates slack channel names for each product.
- **security** - (`github_security_discovery.py`) - security information (eg. Codescanning alerts) extracted from the Github repository
- **workflows** - (`github_workflows_discovery.py`) - Github Workflows extracted from the Github repository
- **teams** - (`github_teams_discovery.py`) - Github teams associated with repositories and the [hmpps-github-teams](https://github.com/ministryofjustice/hmpps-github-teams) Terraform managed repository

Each of these apps are scheduled within the helm configuration.

The script and its suite of associated functions does the following:

## Github Discovery
`github_discovery.py`

This is the main (and original) script. It runs:
- every two hours as an incremental scan (only processing data that may be changed independently of pull requests)
- once per day as a full scan.

The `-f` or `--force-update` option will bypass checking to see if the environment has updated or the main branch will change, and will update all components.

A single component can be processed using `github_component_discovery.py` using the Service Catalogue component name as a parameter.


### Components
- Retrieves a list of all components (microservices) from the service catalogue
- For each component, which has a github repository, it fetches key information (see below) via Github API
- If the environment configuration or main branch SHA has changed since the last scan it retrieves data from Helm and other files within the repository 
- It then updates each component in the service catalogue with the latest data from github.

### Products
- Retrieves a list of all products from the service catalogue
- For each product which has a valid (and non-private) Slack channel ID, it fetches the Slack channel name and updates that field in the service catalogue

### Key information retrieved

This includes:
 - repository teams access (admin/maintain/write)
 - repository branch protection
 - repository language
 - repository visibility
 - repository topics

Retrieval of key data from files (if they exist):
 - `.circleci/config.yml` - hmpps orb version
 - `helm_deploy/` - helm configuration data including dependency chart versions.
 - `applicationinsights.json`/`package.json` - for Azure Application Insights cloudRole_name
 

Retrieval of data from Alertmanager endpoint:
- Production alerts slack channel (based on alert severity in the Helm config)
- Non-production alerts slack channel (also based on alert severity)


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


## Github Teams Discovery

Github teams discovery (`github_team_discovery.py`) populates the **Github Teams** table of the Service Catalogue with team member data based on all the github teams associated with repositories. It checks against the [hmpps-github-teams](https://github.com/ministryofjustice/hmpps-github-teams/tree/main/terraform) terraform configuration and compiles a list of teams.

This essentially calls the function `process_github_teams` within `processes/github_teams.py`

`includes/teams.py` contains functions to processes the teams either from Github or from Terraform data.

## Github Security Discovery

Github Security discovery (`github_security_discovery.py`) scans is a wrapper script for processing components to retrieve security information.

It makes uses of the `batch_process_sc_components` function within `processes/components.py` and, for each component, calls `process_sc_component_security` within `processes/security.py`

This calls a number of functions to retrieve security information (Codescanning alerts and standards compliance) that are added to the Component table in Service Catalogue

## Github Workflows Discovery

Github Workflows discovery (`github_workflows_discovery.py`) scans is a wrapper script for processing components to retrieve information about Github Workflows used by the component.

It makes uses of the `batch_process_sc_components` function within `processes/components.py` and, for each component, calls `process_sc_component_workflows` within `processes/workflows.py`

This scans the `.github` directory of the associated repository and retrieves all workflows that are referenced with a `uses:` key.

These workflows and their references (and a representative location for each one) are added to the Versions field of the Components table in Service Catalogue


## Classes, processes and functions

### Classes

- **AlertManager** (`classes/alertmanager.py`) contains a simple self-contained script that collects and parses data from the Alertmanager Status endpoint
- **CircleCI** (`classes/circleci.py`) contains functions that collect data either from the CircleCI configuration or from endpoints referred to by it
- **GithubSession** (`classes/github.py`) contains custom functions for the discovery script to read and process data from the Github organisation's repositories. It's built on PyGithub
- **HealthServer** (`classes/health.py`) is not used any more - it starts a simple HTTP server that responds to health pings. It's redundant now discovery is running as a crontab
- **ServiceCatalogue** (`classes/service_catalogue.py`) contains functions to read from and write to the Service Catalogue.
- **Slack** (`classes/slack.py`) contains functions to send Slack messages

### Processes

- **Components** (`processes/components.py`) contains the main functions for processing components within the Service Catalogue. These include:
  - `batch_process_sc_components` - the main batch dispatcher that loops through all the components using Python threads for multithreaded operation
  - `process_sc_component` - this is the function that is called by the batch processor for each component
  - `process_independent_component` - gets data for the component independent of branch or environment changes. It runs both on **incremental** and **full** github_discovery runs
  - `process_changed_component` - gets data for the component if a branch or environment is changed or if a **full** github_discovery is run (`force_update=True`)

  Components also initiates the **Environments** (`includes/environments`) and **Helm Config** (`includes/helm.py`) functions, where details of those configurations are read and returned to the main functions

- **Github Teams** (`processes/github_teams.py`) is the script that carries out the actual processing of Github teams

- **products** (`processes/products.py`) contains the main functions for processing products. These include:
  - `batch_process_sc_products` - the main batch dispatcher that loops through all the products using Python threads for multithreaded operation
  - `process_sc_product` - this is the function that's called by the batch processor for each product

- **Security** (`processes/security.py`) contains the main function for processing security statuses for components (`process_sc_component_security`). 
  This calls functions that extract Codescanning alerts from a repository and also checks the repos against standards compliance criteria

- **Workflows** (`processes/workflows.py`) contains the main function for processing workflow statuses for components (`process_sc_component_workflows`).
  This calls functions that extract non-local workflows from the component's Github repository (`get_non_local_actions`)

- **Scheduled Jobs** (`processes/scheduled_jobs.py`) contains functions to update the scheduled_jobs table in Service Catalogue with the status of the various jobs that are run


### Includes

- **Utils** contains re-usable functions that are used across various processes
- **Values** (`includes/values.py`) contains a list of lookups, including standards, actions whitelists and mapping of environment name to type
- **Helm** (`includes/helm.py`) contains functions that read and process the helm configuration
- **Environments** (`includes/environments.py`) contains functions that read and process other environment data, from either Bootstrap `projects.json` or Github Actions Environments
- **Standards** (`includes/standards.py`) contains functions that read and processes various parameters of the repository to determine compliance with standards
- **Teams** (`includes/teams.py`) are functions to processes the teams either from Github or from Terraform data.


## Github tokens
Each Github application has a limit of 15,000 calls per hour. Because some of the Github Discovery processes are quite intensive (each time a file is retrieved from Github it counts as a token use),
some thought was put into how often each discovery needed to take place; running all of them once an hour would simply not work.

Using crontabs defined in the [helm values](helm_deploy) files for each environment,
separate times can be set aside to run more intensive discovery scripts less often.

The general outline is currently:
- `github_discovery.py -f`  - full component/product discovery once per day (Mon-Fri) at 08:30 UTC
- `github_discovery.py` - incremental component/product discovery once every two hours at 45 minutes past, except 06:45 and 08:45 UTC
- `github_teams_discovery.py` - every 20 minutes (it's not too intensive a task)
- `github_security_discovery.py` - once per day (Mon-Fri) at 06:30 UTC 
- `github_workflows_discovery.py` - once a week (Saturday) at 06:30 UTC


## Crontab

The Github Discovery and Github Teams Discovery scripts run on a Kubernetes cluster based on crontab settings within the [helm config](helm_deploy/values-prod.yaml).

Since the Service Catalogue database is copied from prod to dev every night at 11pm, there is no need to run Github Discovery in the dev environment.


## Appendix

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

