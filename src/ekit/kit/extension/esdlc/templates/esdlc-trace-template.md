Write this as a YAML file (strip the fence).

```yaml
# Traceability for one Spec Kit feature: specs/<NNN-name>/trace.yaml
# Written by /speckit.specify (enterprise wrapper). Read by gates spec, scenarios, red, green.
apiVersion: ekit/v1
kind: FeatureTrace
feature: "[NNN-name]"
feature_number: "[NNN]"
prd: "docs/requirements/[slug]"
prd_features: ["FEAT-01"]
acceptance_criteria: ["AC-001", "AC-002"]
business_requirements: ["BR-001", "BR-002"]
```
