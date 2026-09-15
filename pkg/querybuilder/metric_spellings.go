package querybuilder

import (
	"context"
	"strings"

	"github.com/SigNoz/signoz/pkg/flagger"
	"github.com/SigNoz/signoz/pkg/semconv"
	"github.com/SigNoz/signoz/pkg/types/telemetrytypes"
	"github.com/SigNoz/signoz/pkg/valuer"
)

// The span-metrics processor in signoz-otel-collector flattens resource
// attributes into labels with a resource_ prefix. Only the metrics it emits
// carry that layout.
const (
	spanMetricsNamePrefix     = "signoz_"
	spanMetricsResourcePrefix = "resource_"
)

// MetricLabelSpellings returns the storage spellings that can hold
// selector.Name in metric labels: the family members, current first, and
// for a span-metrics metric each member with the resource_ prefix too. A
// name outside an enabled family is returned unchanged. So is a name the
// selector leaves ambiguous.
func MetricLabelSpellings(selector telemetrytypes.FieldKeySelector) []string {
	lookup := selector
	lookup.Name = strings.TrimPrefix(selector.Name, spanMetricsResourcePrefix)
	members := semconv.Members(semconv.KindAttribute, lookup)
	if len(members) <= 1 {
		return []string{selector.Name}
	}
	if selector.MetricContext == nil || !strings.HasPrefix(selector.MetricContext.MetricName, spanMetricsNamePrefix) {
		return members
	}
	spellings := make([]string, 0, len(members)*2)
	for _, member := range members {
		spellings = append(spellings, member, spanMetricsResourcePrefix+member)
	}
	return spellings
}

// FamilyMetricNames returns the storage names a metric query must read: the
// requested name plus the other names of its metric-name family when the
// resolve_semconv_families flag is on for the org.
func FamilyMetricNames(ctx context.Context, orgID valuer.UUID, fl flagger.Flagger, metricName string) []string {
	if !SemconvFamiliesEnabled(ctx, orgID, fl) {
		return []string{metricName}
	}
	return semconv.Members(semconv.KindMetric, telemetrytypes.FieldKeySelector{
		Name:         metricName,
		Signal:       telemetrytypes.SignalMetrics,
		FieldContext: telemetrytypes.FieldContextMetric,
	})
}
