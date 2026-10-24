{{/* The service this release runs. Everything is named after it, so other pods reach it at http://<service>. */}}
{{- define "school.name" -}}
{{- required "service.name is required (auth, admission, student, fee, attendance or notification)" .Values.service.name -}}
{{- end -}}

{{- define "school.serviceAccountName" -}}
{{- default (include "school.name" .) .Values.serviceAccount.name -}}
{{- end -}}

{{/* Image: <registry>/school/<service>:<tag>, or pinned by digest. "latest" and an empty tag are refused. */}}
{{- define "school.image" -}}
{{- $repo := default (printf "%s/school/%s" (required "global.imageRegistry is required" .Values.global.imageRegistry) (include "school.name" .)) .Values.image.repository -}}
{{- $tag := required "image.tag is required: the git commit SHA built by CI" .Values.image.tag -}}
{{- if eq $tag "latest" -}}{{- fail "image.tag must not be 'latest': a tag has to identify exactly one build" -}}{{- end -}}
{{- if .Values.image.digest -}}{{ $repo }}@{{ .Values.image.digest }}{{- else -}}{{ $repo }}:{{ $tag }}{{- end -}}
{{- end -}}

{{- define "school.selectorLabels" -}}
app.kubernetes.io/name: {{ include "school.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end -}}

{{/* Labels on every object. `component` is passed in: api, worker, migration, cron. */}}
{{- define "school.labels" -}}
{{ include "school.selectorLabels" .root }}
app.kubernetes.io/component: {{ .component }}
app.kubernetes.io/version: {{ .root.Values.image.tag | quote }}
app.kubernetes.io/part-of: school
app.kubernetes.io/managed-by: {{ .root.Release.Service }}
helm.sh/chart: {{ printf "%s-%s" .root.Chart.Name .root.Chart.Version | quote }}
{{- end -}}

{{/*
The settings every pod of this service gets. Only NON-secret values: ARNs and URLs. The pod reads the secrets themselves from
Secrets Manager with its own IAM role (EKS Pod Identity), so no secret is ever stored in Kubernetes.
Called with: (dict "root" $ "dbArn" <the Secrets Manager ARN of the database login to use>)
*/}}
{{- define "school.configData" -}}
{{- $v := .root.Values -}}
{{- $g := $v.global -}}
ENVIRONMENT: {{ $g.environment | quote }}
LOG_LEVEL: {{ $g.logLevel | quote }}
AWS_REGION: {{ $g.region | quote }}
AUTO_CREATE_TABLES: "false"
DB_SECRET_ARN: {{ required "a database login ARN is required" .dbArn | quote }}
{{- if $v.features.jwtPublicKey }}
JWT_PUBLIC_KEY_SECRET_ARN: {{ required "global.secrets.jwtPublicKeyArn is required" $g.secrets.jwtPublicKeyArn | quote }}
{{- end }}
{{- if $v.features.jwtPrivateKey }}
JWT_PRIVATE_KEY_SECRET_ARN: {{ required "global.secrets.jwtPrivateKeyArn is required" $g.secrets.jwtPrivateKeyArn | quote }}
{{- end }}
JWT_ISSUER: {{ $g.jwtIssuer | quote }}
JWT_AUDIENCE: {{ $g.jwtAudience | quote }}
{{- if ne $v.features.events "none" }}
SQS_QUEUE_URL: {{ required "global.eventsQueueUrl is required" $g.eventsQueueUrl | quote }}
{{- end }}
{{- if $v.features.notificationsTopic }}
SNS_TOPIC_ARN: {{ required "global.notificationsTopicArn is required" $g.notificationsTopicArn | quote }}
{{- end }}
{{- if $v.features.studentApi }}
STUDENT_SERVICE_URL: "http://student"
{{- end }}
{{- range $key, $value := $v.config }}
{{ $key }}: {{ $value | quote }}
{{- end }}
{{- end -}}

{{- define "school.dbAppArn" -}}
{{- index (required "global.secrets.dbAppArns is required" .Values.global.secrets.dbAppArns) (include "school.name" .) | required (printf "no runtime database login ARN for service %s in global.secrets.dbAppArns" (include "school.name" .)) -}}
{{- end -}}

{{- define "school.dbMigratorArn" -}}
{{- index (required "global.secrets.dbMigratorArns is required" .Values.global.secrets.dbMigratorArns) (include "school.name" .) | required (printf "no migrator login ARN for service %s in global.secrets.dbMigratorArns" (include "school.name" .)) -}}
{{- end -}}

{{/* The restricted pod profile. Matches the Kubernetes "restricted" Pod Security Standard, which the namespace enforces. */}}
{{- define "school.podSecurityContext" -}}
runAsNonRoot: true
runAsUser: 10001
runAsGroup: 10001
seccompProfile:
  type: RuntimeDefault
{{- end -}}

{{- define "school.containerSecurityContext" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: ["ALL"]
{{- end -}}

{{/* The only writable place: an in-memory /tmp. */}}
{{- define "school.tmpVolume" -}}
- name: tmp
  emptyDir:
    medium: Memory
    sizeLimit: 64Mi
{{- end -}}

{{- define "school.tmpMount" -}}
- name: tmp
  mountPath: /tmp
{{- end -}}

{{/* Spread replicas across availability zones, then across nodes. */}}
{{- define "school.topologySpread" -}}
- maxSkew: 1
  topologyKey: topology.kubernetes.io/zone
  whenUnsatisfiable: ScheduleAnyway
  labelSelector:
    matchLabels:
      {{- include "school.selectorLabels" .root | nindent 6 }}
      app.kubernetes.io/component: {{ .component }}
- maxSkew: 1
  topologyKey: kubernetes.io/hostname
  whenUnsatisfiable: ScheduleAnyway
  labelSelector:
    matchLabels:
      {{- include "school.selectorLabels" .root | nindent 6 }}
      app.kubernetes.io/component: {{ .component }}
{{- end -}}
