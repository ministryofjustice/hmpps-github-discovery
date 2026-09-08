{{- define "deploymentAnalyticsCronJob.envs" -}}
{{- if or .deploymentAnalyticsCronJob.namespace_secrets .deploymentAnalyticsCronJob.env -}}
env:
{{- if .deploymentAnalyticsCronJob.namespace_secrets -}}
{{- include "common.envFromSecretMap" .deploymentAnalyticsCronJob.namespace_secrets | nindent 2 -}}
{{- end }}
{{- if .deploymentAnalyticsCronJob.env -}}
{{- include "common.envFromLiteralMap" .deploymentAnalyticsCronJob.env | nindent 2 -}}
{{- end }}
{{- end -}}
{{- end }}
