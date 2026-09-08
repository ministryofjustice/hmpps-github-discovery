{{- define "common.envFromSecretMap" -}}
{{- range $secret, $envs := . -}}
  {{- range $key, $val := $envs }}
  - name: {{ $key }}
    valueFrom:
      secretKeyRef:
        key: {{ trimSuffix "?" $val }}
        name: {{ $secret }}{{ if hasSuffix "?" $val }}
        optional: true{{ end }}
  {{- end }}
{{- end }}
{{- end -}}

{{- define "common.envFromLiteralMap" -}}
{{- range $key, $val := . -}}
  - name: {{ $key }}
    value: {{ quote $val }}
{{- end }}
{{- end -}}

{{- define "discoveryCronJob.envs" -}}
{{- if or .github_discovery.namespace_secrets .discoveryCronJob.env -}}
env:
{{- if .github_discovery.namespace_secrets -}}
{{- include "common.envFromSecretMap" .github_discovery.namespace_secrets | nindent 2 -}}
{{- end }}
{{- if .discoveryCronJob.env -}}
{{- include "common.envFromLiteralMap" .discoveryCronJob.env | nindent 2 -}}
{{- end }}
{{- end -}}
{{- end }}
