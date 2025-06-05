{{- define "github-discovery.envs" -}}
{{- if or .github-discovery.namespace_secrets .github-discovery.env -}}
env:
{{- if .github-discovery.namespace_secrets -}}
{{- range $secret, $envs := .github-discovery.namespace_secrets }}
  {{- range $key, $val := $envs }}
  - name: {{ $key }}
    valueFrom:
      secretKeyRef:
        key: {{ trimSuffix "?" $val }}
        name: {{ $secret }}{{ if hasSuffix "?" $val }}
        optional: true{{ end }}  {{- end }}
{{- end }}
{{- end }}
{{- if .github-discovery.env -}}
{{- range $key, $val := .github-discovery.env }}
  - name: {{ $key }}
    value: {{ quote $val }}
{{- end }}
{{- end }}
{{- end -}}
{{- end -}}
