# Edit desired-state/ and config.json, then run `make install`.
# make config creates config.json when it is missing. It does not overwrite it.
# install runs config, then test. test checks the YAML and config.json.

.PHONY: test config install uninstall clean

UNIT_DIR := $(HOME)/.config/systemd/user
UNIT := $(UNIT_DIR)/house-lights.service
CONFIG := $(CURDIR)/config.json
STATE := $(CURDIR)/desired-state/daemon.json

test:
	uv run python -m unittest discover -s tests -v

config:
	python3 contrib/make_config.py "$(CONFIG)"

install:
	$(MAKE) config
	$(MAKE) test
	uv tool install --force "$(CURDIR)"
	install -d "$(UNIT_DIR)"
	set -eu; \
	bin="$$(uv tool dir --bin)/house-lights"; \
	test -x "$$bin"; \
	sed -e "s|@BIN@|$$bin|g" -e "s|@ROOT@|$(CURDIR)|g" contrib/house-lights.service.in > "$(UNIT)"; \
	systemctl --user daemon-reload; \
	rm -f "$(STATE)"; \
	systemctl --user enable house-lights.service; \
	systemctl --user restart house-lights.service; \
	printf '%s\n' "Installed house-lights and restarted the daemon."

uninstall:
	-systemctl --user disable --now house-lights.service
	rm -f "$(UNIT)"
	-systemctl --user daemon-reload
	rm -f "$(STATE)"
	-uv tool uninstall house-lights

clean:
	rm -rf .venv dist build src/house_lights.egg-info src/*.egg-info
	find src tests -type d -name __pycache__ -exec rm -rf {} +
