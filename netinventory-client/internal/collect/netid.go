package collect

import (
	"crypto/sha256"
	"fmt"
	"sort"
	"strings"
)

// NetworkContext contains fields used to derive a NetID.
type NetworkContext struct {
	InterfaceType string   // eth, wifi
	Subnets       []string // e.g., 192.168.1.0/24
	GatewayIP     string
	GatewayMAC    string
	ExternalIP    string // public IP address
	SSID          string
	BSSID         string
}

// DeriveNetID creates a stable, fuzzy identifier for a network context.
func DeriveNetID(ctx NetworkContext) string {
	var parts []string

	parts = append(parts, "type:"+ctx.InterfaceType)

	// Sort subnets to ensure stability
	sort.Strings(ctx.Subnets)
	for _, s := range ctx.Subnets {
		parts = append(parts, "subnet:"+s)
	}

	if ctx.GatewayIP != "" {
		parts = append(parts, "gw_ip:"+ctx.GatewayIP)
	}
	if ctx.GatewayMAC != "" {
		parts = append(parts, "gw_mac:"+strings.ToLower(ctx.GatewayMAC))
	}
	// External IP is a strong signal for distinguishing networks (e.g. Home vs Work)
	if ctx.ExternalIP != "" {
		parts = append(parts, "ext_ip:"+ctx.ExternalIP)
	}
	if ctx.SSID != "" {
		parts = append(parts, "ssid:"+ctx.SSID)
	}
	if ctx.BSSID != "" {
		parts = append(parts, "bssid:"+strings.ToLower(ctx.BSSID))
	}

	raw := strings.Join(parts, "|")
	hash := sha256.Sum256([]byte(raw))

	return fmt.Sprintf("%x", hash[:8]) // Use 16-char hex string as ID
}
