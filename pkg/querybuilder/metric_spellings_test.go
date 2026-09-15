package querybuilder

import (
	"context"
	"testing"

	"github.com/SigNoz/signoz/pkg/flagger"
	"github.com/SigNoz/signoz/pkg/flagger/flaggertest"
	"github.com/SigNoz/signoz/pkg/types/telemetrytypes"
	"github.com/SigNoz/signoz/pkg/valuer"
	"github.com/stretchr/testify/assert"
)

func TestMetricLabelSpellingsReturnsTheFamilyMembers(t *testing.T) {
	selector := telemetrytypes.FieldKeySelector{
		Name:          "deployment.environment",
		Signal:        telemetrytypes.SignalMetrics,
		MetricContext: &telemetrytypes.MetricContext{MetricName: "k8s.pod.cpu.usage"},
	}

	assert.Equal(t, []string{"deployment.environment.name", "deployment.environment"}, MetricLabelSpellings(selector))
}

func TestMetricLabelSpellingsAddsTheResourcePrefixForSpanMetrics(t *testing.T) {
	selector := telemetrytypes.FieldKeySelector{
		Name:          "resource_deployment.environment",
		Signal:        telemetrytypes.SignalMetrics,
		MetricContext: &telemetrytypes.MetricContext{MetricName: "signoz_calls_total"},
	}

	assert.Equal(t, []string{
		"deployment.environment.name", "resource_deployment.environment.name",
		"deployment.environment", "resource_deployment.environment",
	}, MetricLabelSpellings(selector), "a span-metrics label reads with and without the resource_ prefix")
}

func TestMetricLabelSpellingsStaysLiteralOutsideTheVocabulary(t *testing.T) {
	selector := telemetrytypes.FieldKeySelector{
		Name:   "http.route",
		Signal: telemetrytypes.SignalMetrics,
	}

	assert.Equal(t, []string{"http.route"}, MetricLabelSpellings(selector))
}

func TestFamilyMetricNames(t *testing.T) {
	on := flaggertest.WithBooleanFlags(t, map[string]bool{
		flagger.FeatureResolveSemconvFamilies.String(): true,
	})
	assert.Equal(t, []string{"k8s.pod.cpu.usage", "k8s.pod.cpu.utilization"}, FamilyMetricNames(context.Background(), valuer.UUID{}, on, "k8s.pod.cpu.utilization"))
	assert.Equal(t, []string{"k8s.pod.cpu.usage", "k8s.pod.cpu.utilization"}, FamilyMetricNames(context.Background(), valuer.UUID{}, on, "k8s.pod.cpu.usage"))
	assert.Equal(t, []string{"http.server.duration"}, FamilyMetricNames(context.Background(), valuer.UUID{}, on, "http.server.duration"))

	off := flaggertest.WithBooleanFlags(t, map[string]bool{})
	assert.Equal(t, []string{"k8s.pod.cpu.utilization"}, FamilyMetricNames(context.Background(), valuer.UUID{}, off, "k8s.pod.cpu.utilization"))
}
