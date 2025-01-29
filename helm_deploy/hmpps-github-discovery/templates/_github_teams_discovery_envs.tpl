{{ define "githubTeamsDiscovery.envs" }}
{{ if .Values.generic-service.namespace_secrets }}
env:
{{ range $namespace, $secrets := .Values.generic-service.namespace_secrets }}
  - name: example
    valueFrom:
      secretKeyRef:
        key: example-key
        name: {{ $namespace }}
{{ end }}
{{ end }}
{{ end }}
