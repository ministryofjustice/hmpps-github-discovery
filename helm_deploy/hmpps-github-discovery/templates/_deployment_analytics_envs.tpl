{{- define "deploymentAnalyticsCronJob.envs" -}}
{{- if or .github_discovery.namespace_secrets .deploymentAnalyticsCronJob.namespace_secrets .deploymentAnalyticsCronJob.env -}}
env:
{{- if .github_discovery.namespace_secrets }}
{{ include "shared.secretEnvList" .github_discovery.namespace_secrets | nindent 2 }}
{{- end }}
{{- if .deploymentAnalyticsCronJob.namespace_secrets }}
{{ include "shared.secretEnvList" .deploymentAnalyticsCronJob.namespace_secrets | nindent 2 }}
{{- end }}
{{- if .deploymentAnalyticsCronJob.env }}
{{ include "shared.literalEnvList" .deploymentAnalyticsCronJob.env | nindent 2 }}
{{- end }}
{{- end -}}
{{- end }}
