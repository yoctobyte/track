package plugins

import (
	"context"
	"encoding/json"
	"fmt"
	"os/exec"
)

// ScriptPlugin runs an external script (e.g., Python) to gather data.
type ScriptPlugin struct {
	pluginName string
	command    string
	args       []string
}

func NewScriptPlugin(name string, command string, args ...string) *ScriptPlugin {
	return &ScriptPlugin{
		pluginName: name,
		command:    command,
		args:       args,
	}
}

func (p *ScriptPlugin) Name() string { return p.pluginName }

func (p *ScriptPlugin) Run(ctx context.Context) (Result, error) {
	cmd := exec.CommandContext(ctx, p.command, p.args...)
	out, err := cmd.CombinedOutput()

	if err != nil {
		return Result{
			Name:    p.Name(),
			Success: false,
			Error:   fmt.Sprintf("script failed: %v\nOutput: %s", err, string(out)),
		}, nil
	}

	// Try to parse output as JSON facts, otherwise treat as raw
	var facts map[string]interface{}
	if err := json.Unmarshal(out, &facts); err == nil {
		return Result{
			Name:    p.Name(),
			Success: true,
			Facts:   facts,
		}, nil
	}

	return Result{
		Name:    p.Name(),
		Success: true,
		Raw:     string(out),
	}, nil
}
