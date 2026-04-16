package plugins

import (
	"context"
)

// GPSProvider is an interface to avoid circular dependency on monitor.
type GPSProvider interface {
	GetFix() map[string]interface{}
}

// GPSPlugin captures coordinates during snapshots.
type GPSPlugin struct {
	Provider GPSProvider
}

func (p *GPSPlugin) Name() string { return "gps_location" }

func (p *GPSPlugin) Run(ctx context.Context) (Result, error) {
	fix := p.Provider.GetFix()
	return Result{
		Name:    p.Name(),
		Success: true,
		Facts:   fix,
	}, nil
}
