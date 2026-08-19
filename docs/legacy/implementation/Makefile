# U55C Vitis build for Steane decoder kernel

TARGET ?= hw
PLATFORM ?= xilinx_u55c_gen3x16_xdma_3_202210_1

CXX ?= g++
VPP ?= v++

SRC_DIR := src
BUILD_DIR := build/$(TARGET)
DATA_DIR := data
SYNDROMES_FILE ?= $(DATA_DIR)/syndromes.txt
LUT_FILE ?= $(DATA_DIR)/decoder_lut.hex

KERNEL_NAME := steane_decoder_kernel
KERNEL_SRC := $(SRC_DIR)/steane_decoder_kernel.cpp
HOST_SRC := $(SRC_DIR)/host_decoder.cpp

XO := $(BUILD_DIR)/$(KERNEL_NAME).xo
XCLBIN := $(BUILD_DIR)/$(KERNEL_NAME).$(TARGET).xclbin
HOST_EXE := $(BUILD_DIR)/host_decoder

XRT_PATH ?= $(XILINX_XRT)
CXXFLAGS := -std=c++17 -O2 -Wall -I$(XRT_PATH)/include
LDFLAGS := -L$(XRT_PATH)/lib -lOpenCL -pthread -lrt

VPP_COMPILE_FLAGS := -t $(TARGET) --platform $(PLATFORM) -k $(KERNEL_NAME) --save-temps
VPP_LINK_FLAGS := -t $(TARGET) --platform $(PLATFORM)

.PHONY: all host xclbin run run-only clean

all: host xclbin

$(BUILD_DIR):
	mkdir -p $(BUILD_DIR)

host: $(BUILD_DIR)
	$(CXX) $(CXXFLAGS) $(HOST_SRC) -o $(HOST_EXE) $(LDFLAGS)

$(XO): $(KERNEL_SRC) | $(BUILD_DIR)
	$(VPP) -c $(VPP_COMPILE_FLAGS) -o $@ $<

$(XCLBIN): $(XO)
	$(VPP) -l $(VPP_LINK_FLAGS) -o $@ $<

xclbin: $(XCLBIN)

run: all
	@if [ -z "$$XCL_EMULATION_MODE" ] && [ "$(TARGET)" != "hw" ]; then \
		echo "Set XCL_EMULATION_MODE=sw_emu or hw_emu for emulation runs"; \
		exit 1; \
	fi
	$(HOST_EXE) $(XCLBIN) $(SYNDROMES_FILE) $(LUT_FILE)

run-only:
	@if [ ! -x "$(HOST_EXE)" ]; then \
		echo "Missing host executable: $(HOST_EXE)"; \
		echo "Build first with: make TARGET=$(TARGET) PLATFORM=$(PLATFORM) all"; \
		exit 1; \
	fi
	@if [ ! -f "$(XCLBIN)" ]; then \
		echo "Missing xclbin: $(XCLBIN)"; \
		echo "Build first with: make TARGET=$(TARGET) PLATFORM=$(PLATFORM) all"; \
		exit 1; \
	fi
	@if [ -z "$$XCL_EMULATION_MODE" ] && [ "$(TARGET)" != "hw" ]; then \
		echo "Set XCL_EMULATION_MODE=sw_emu or hw_emu for emulation runs"; \
		exit 1; \
	fi
	$(HOST_EXE) $(XCLBIN) $(SYNDROMES_FILE) $(LUT_FILE)

clean:
	rm -rf build
