{{ define "githubTeamsDiscovery.envs" }}
env:
- name: example
  valueFrom:
    secretKeyRef:
      key: example-key
      name: example-namespace
{{ end }}
