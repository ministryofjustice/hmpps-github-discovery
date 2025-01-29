{{ define "githubTeamsDiscovery.envs" }}
{{ if .Values.generic-service.namespace_secrets }}
# Debug output
{{ .Values.generic-service.namespace_secrets | toYaml }}
env:
- name: example
  valueFrom:
    secretKeyRef:
      key: example-key
      name: example-namespace
{{ end }}
{{ end }}
