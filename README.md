# HMPPS Github Discovery

This app queries the github api for information about hmpps projects and pushes that information into the hmpps service catalogue.

The app does the following:
- Retrieves a list of all components (microservices) from the service catalogue.
- For each component, which has a github repository, it fetches key information (see below) via github api.
- It then updates each component in the service catalogue with the latest data from github.

Key information retrieved includes:
 - repository teams access (admin/maintain/write)
 - repository branch protection
 - repository language
 - repository visibility
 - repository topics

Retrieval of key data from files (if they exists):
 - .circleci/config.yml - hmpps orb version
 - helm_deploy/ - various data including dependency chart versions.
 - applicationinsights.json - for azure app insights cloudRole_name
 - package.json - for azure app insights cloudRole_name

