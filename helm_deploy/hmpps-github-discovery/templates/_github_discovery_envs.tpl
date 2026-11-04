{{- define "shared.secretEnvList" -}}
{{- range $secret, $envs := . }}
{{- range $key, $val := $envs }}
- name: {{ $key }}
  valueFrom:
    secretKeyRef:
      name: {{ $secret }}
      key: {{ trimSuffix "?" $val }}
      {{- if hasSuffix "?" $val }}
      optional: true
      {{- end }}
{{- end }}
{{- end }}
{{- end -}}

{{- define "shared.literalEnvList" -}}
{{- range $key, $val := . }}
- name: {{ $key }}
  value: {{ quote $val }}
{{- end }}
{{- end -}}

{{- define "discoveryCronJob.envs" -}}
{{- if or .github_discovery.namespace_secrets .discoveryCronJob.env -}}
env:
{{- if .github_discovery.namespace_secrets }}
{{ include "shared.secretEnvList" .github_discovery.namespace_secrets | nindent 2 }}
{{- end }}
{{- if .discoveryCronJob.env }}
{{ include "shared.literalEnvList" .discoveryCronJob.env | nindent 2 }}
{{- end }}
{{- end -}}
{{- end }}
