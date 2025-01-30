{{- define "discoveryCronJob.envs" -}}
{{- if and .Values.discoveryCronJob (hasKey .Values.discoveryCronJob "namespace_secrets") -}}
env:
{{- range $namespace, $secrets := .Values.discoveryCronJob.namespace_secrets }}
  {{- if eq $namespace "hmpps-github-discovery" }}
    {{- range $key, $val := $secrets }}
    - name: {{ $key }}
      valueFrom:
        secretKeyRef:
          key: {{ trimSuffix "?" $val }}
          name: {{ $namespace }}{{ if hasSuffix "?" $val }}
          optional: true{{ end }}
    {{- end }}
  {{- end }}
{{- end }}
{{- end }}
{{- end }}