# Edit the YAML in desired-state/, then run `make install`.
# Another directory can be selected with --desired-state or the config key desired_state.
# install runs test first. test checks that the YAML loads.

.PHONY: test install uninstall clean

PREFIX := $(HOME)/.local
DESIRED_STATE_DIR := $(PREFIX)/share/house-lights/desired-state
CONFIG_DIR := $(HOME)/.config/house-lights
STATE_DIR := $(PREFIX)/state/house-lights
UNIT_DIR := $(HOME)/.config/systemd/user
CONFIG := $(CONFIG_DIR)/config.json
STATE := $(STATE_DIR)/daemon.json
UNIT := $(UNIT_DIR)/house-lights.service

test:
	uv run python -m unittest discover -s tests -v

install: test
	uv tool install --force "$(CURDIR)"
	install -d "$(CONFIG_DIR)" "$(STATE_DIR)" "$(UNIT_DIR)"
	rm -rf "$(DESIRED_STATE_DIR)"
	install -d "$(DESIRED_STATE_DIR)"
	cp -a desired-state/. "$(DESIRED_STATE_DIR)/"
	if [ ! -f "$(CONFIG)" ]; then install -m 600 config.example.json "$(CONFIG)"; fi
	set -eu; \
	bin="$$(uv tool dir --bin)/house-lights"; \
	test -x "$$bin"; \
	sed "s|@BIN@|$$bin|g" contrib/house-lights.service.in > "$(UNIT)"; \
	systemctl --user daemon-reload; \
	if python3 "$(CURDIR)/contrib/config_ready.py" "$(CONFIG)"; then \
		rm -f "$(STATE)"; \
		systemctl --user enable house-lights.service; \
		systemctl --user restart house-lights.service; \
		printf '%s\n' "Installed house-lights and restarted the daemon."; \
	else \
		printf '%s\n' "Installed the command and the service file. Edit $(CONFIG), then run make install again."; \
		exit 1; \
	fi

uninstall:
	-systemctl --user disable --now house-lights.service
	rm -f "$(UNIT)"
	-systemctl --user daemon-reload
	rm -rf "$(DESIRED_STATE_DIR)"
	rm -f "$(STATE)"
	-uv tool uninstall house-lights

clean:
	rm -rf .venv dist build src/house_lights.egg-info src/*.egg-info
	find src tests -type d -name __pycache__ -exec rm -rf {} +
