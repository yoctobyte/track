package collect

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"time"

	"netinventory/internal/event"
)

// Snapshot represents a point-in-time capture of network state.
type Snapshot struct {
	ID        string        `json:"id"`
	Timestamp time.Time     `json:"timestamp"`
	Triggers  []event.Event `json:"triggers"`
	NetID     string        `json:"net_id"`
	Outcome   string        `json:"outcome"` // e.g., "success", "partial", "interrupted"

	// Data captured during the snapshot
	Data map[string]interface{} `json:"data"`

	// Metadata
	Metadata map[string]interface{} `json:"metadata"`
}

// Store handles persistence of snapshots.
type Store struct {
	baseDir string
}

// NewStore creates a new snapshot store.
func NewStore(baseDir string) (*Store, error) {
	if err := os.MkdirAll(baseDir, 0755); err != nil {
		return nil, fmt.Errorf("failed to create store directory: %w", err)
	}
	return &Store{baseDir: baseDir}, nil
}

// Save writes a snapshot to disk in an immutable fashion.
func (s *Store) Save(snap *Snapshot) error {
	data, err := json.MarshalIndent(snap, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal snapshot: %w", err)
	}

	// Filename: <timestamp>_<id>.json
	filename := fmt.Sprintf("%d_%s.json", snap.Timestamp.Unix(), snap.ID)
	path := filepath.Join(s.baseDir, filename)

	// Write to a temporary file first, then rename to ensure atomicity.
	tmpPath := path + ".tmp"
	if err := os.WriteFile(tmpPath, data, 0644); err != nil {
		return fmt.Errorf("failed to write snapshot: %w", err)
	}

	if err := os.Rename(tmpPath, path); err != nil {
		return fmt.Errorf("failed to finalize snapshot: %w", err)
	}

	return nil
}

// SetActive updates a consolidated metadata file with the latest active network ID.
func (s *Store) SetActive(netID string) error {
	active := map[string]interface{}{
		"active_net_id": netID,
		"updated_at":    time.Now().Format(time.RFC3339),
	}
	data, err := json.MarshalIndent(active, "", "  ")
	if err != nil {
		return err
	}

	path := filepath.Join(s.baseDir, "active.json")
	return os.WriteFile(path, data, 0644)
}

// GetPath returns the file path for a snapshot ID.
func (s *Store) GetPath(id string) string {
	// Note: In Phase 1, we might need a better way to lookup if we don't have the timestamp.
	// For now, this is a placeholder for retrieving data.
	return ""
}
