CC ?= cc
CFLAGS ?= -std=c11 -Wall -Wextra -Werror -pedantic -Iinclude
BUILD_DIR := build
CORE := src/fsm.c
SCENARIOS := $(wildcard ../tests/scenarios/*.csv)

.PHONY: all test scenarios clean

all: $(BUILD_DIR)/test_fsm $(BUILD_DIR)/scenario_runner

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

$(BUILD_DIR)/test_fsm: $(CORE) tests/test_fsm.c include/fsm.h | $(BUILD_DIR)
	$(CC) $(CFLAGS) $(CORE) tests/test_fsm.c -o $@

$(BUILD_DIR)/scenario_runner: $(CORE) tests/scenario_runner.c include/fsm.h | $(BUILD_DIR)
	$(CC) $(CFLAGS) $(CORE) tests/scenario_runner.c -o $@

test: $(BUILD_DIR)/test_fsm
	./$(BUILD_DIR)/test_fsm

scenarios: $(BUILD_DIR)/scenario_runner
	./$(BUILD_DIR)/scenario_runner $(SCENARIOS)

clean:
	rm -rf $(BUILD_DIR)
