{{ define "githubTeamsDiscovery.envs" }}
{{ if .Values.generic-service.namespace_secrets }}
env:
{{ range $namespace, $secrets := .Values.generic-service.namespace_secrets }}
  {{ if eq $namespace "hmpps-github-discovery" }}
    {{ range $key, $val := $secrets }}
    - name: {{ $key }}
      valueFrom:
        secretKeyRef:
          key: {{ trimSuffix "?" $val }}
          name: {{ $namespace }}{{ if hasSuffix "?" $val }}
          optional: true{{ end }}
    {{ end }}
  {{ end }}
{{ end }}
{{ end }}
{{ end }}
