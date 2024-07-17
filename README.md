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


## Requirements
 - Service Catalogue API token
 - Github app ID / installation ID / private key
 - Circle CI token
 - Slackbot token (this uses the [`hmpps-sre-app`](https://api.slack.com/apps/A07BZTDHRNK/general) Slack app)


