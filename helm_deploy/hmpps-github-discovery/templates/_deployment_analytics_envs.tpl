{{- define "deploymentAnalyticsCronJob.envs" -}}
{{- if or .deploymentAnalyticsCronJob.namespace_secrets .deploymentAnalyticsCronJob.env -}}
env:
{{- if .deploymentAnalyticsCronJob.namespace_secrets }}
{{ include "shared.secretEnvList" .deploymentAnalyticsCronJob.namespace_secrets | nindent 2 }}
{{- end }}
{{- if .deploymentAnalyticsCronJob.env }}
{{ include "shared.literalEnvList" .deploymentAnalyticsCronJob.env | nindent 2 }}
{{- end }}
{{- end -}}
{{- end }}
