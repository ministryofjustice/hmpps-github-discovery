{{- define "deploymentAnalyticsCronJob.envs" -}}
{{- if or .github_discovery.namespace_secrets .deploymentAnalyticsCronJob.env -}}
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
{{- if .deploymentAnalyticsCronJob.env -}}
{{- range $key, $val := .deploymentAnalyticsCronJob.env }}
  - name: {{ $key }}
    value: {{ quote $val }}
{{- end }}
{{- end }}
{{- end -}}
{{- end -}}
