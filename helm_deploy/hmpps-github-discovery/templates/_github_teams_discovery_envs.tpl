{{ define "githubTeamsDiscovery.envs" }}
{{ if .Values.generic-service.namespace_secrets }}
env:
- name: example
  valueFrom:
    secretKeyRef:
      key: example-key
      name: example-namespace
{{ end }}
{{ end }}
