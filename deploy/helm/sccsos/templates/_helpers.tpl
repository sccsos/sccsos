{{- define "sccsos.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{- define "sccsos.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{- define "sccsos.labels" -}}
helm.sh/chart: {{ include "sccsos.name" . }}-{{ .Chart.Version | replace "+" "_" }}
app.kubernetes.io/name: {{ include "sccsos.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{- define "sccsos.selectorLabels" -}}
app.kubernetes.io/name: {{ include "sccsos.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{- define "sccsos.hermesContainer" -}}
{{- if eq .Values.mode "slim+sidecar" }}
- name: hermes-sidecar
  image: "{{ .Values.hermes.image.repository }}:{{ .Values.hermes.image.tag }}"
  imagePullPolicy: {{ .Values.hermes.image.pullPolicy }}
  env:
    - name: HERMES_MODE
      value: "serve"
    - name: HERMES_PORT
      value: "8081"
  resources:
    {{- toYaml .Values.hermes.resources | nindent 4 }}
{{- end }}
{{- end }}

{{- define "sccsos.imageTag" -}}
{{- if eq .Values.mode "slim+sidecar" }}
{{- .Values.image.slimTag }}
{{- else }}
{{- .Values.image.tag }}
{{- end }}
{{- end }}
