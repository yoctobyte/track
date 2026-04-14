package plugins

import (
	"context"
	"time"
)

// Result represents the output of a plugin.
type Result struct {
	Name      string                 `json:"name"`
	Success   bool                   `json:"success"`
	StartTime time.Time              `json:"start_time"`
	EndTime   time.Time              `json:"end_time"`
	Duration  string                 `json:"duration"`
	Facts     map[string]interface{} `json:"facts"`
	Raw       string                 `json:"raw,omitempty"`
	Error     string                 `json:"error,omitempty"`
}

// Plugin is the interface for all data collectors.
type Plugin interface {
	Name() string
	Run(ctx context.Context) (Result, error)
}

// Runner executes plugins with isolation and timeouts.
type Runner struct {
	Timeout time.Duration
}

// NewRunner creates a new plugin runner.
func NewRunner(timeout time.Duration) *Runner {
	return &Runner{Timeout: timeout}
}

// Run executes a list of plugins.
func (r *Runner) Run(plugins []Plugin) []Result {
	results := make([]Result, len(plugins))
	
	for i, p := range plugins {
		start := time.Now()
		
		ctx, cancel := context.WithTimeout(context.Background(), r.Timeout)
		res, err := p.Run(ctx)
		cancel()

		if err != nil {
			res.Name = p.Name()
			res.Success = false
			res.Error = err.Error()
		}
		
		res.StartTime = start
		res.EndTime = time.Now()
		res.Duration = res.EndTime.Sub(start).String()
		results[i] = res
	}
	
	return results
}
