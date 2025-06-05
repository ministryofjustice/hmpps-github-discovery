{{- define "github_discovery.envs" -}}
{{- if or .github_discovery.namespace_secrets .github_discovery.env -}}
env:
{{- if .github_discovery.namespace_secrets -}}
{{- range $secret, $envs := .github_discovery.namespace_secrets }}
  {{- range $key, $val := $envs }}
  - name: {{ $key }}
    valueFrom:
      secretKeyRef:
        key: {{ trimSuffix "?" $val }}
        name: {{ $secret }}{{ if hasSuffix "?" $val }}
        optional: true{{ end }}  {{- end }}
{{- end }}
{{- end }}
{{- if .github_discovery.env -}}
{{- range $key, $val := .github_discovery.env }}
  - name: {{ $key }}
    value: {{ quote $val }}
{{- end }}
{{- end }}
{{- end -}}
{{- end -}}
