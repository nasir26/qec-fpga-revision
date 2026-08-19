#define CL_HPP_TARGET_OPENCL_VERSION 120
#define CL_HPP_MINIMUM_OPENCL_VERSION 120

#include <CL/cl2.hpp>

#include <cctype>
#include <cstdint>
#include <array>
#include <chrono>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

std::string trim_copy(const std::string& input) {
    size_t start = 0;
    while (start < input.size() && std::isspace(static_cast<unsigned char>(input[start]))) {
        ++start;
    }

    size_t end = input.size();
    while (end > start && std::isspace(static_cast<unsigned char>(input[end - 1]))) {
        --end;
    }

    return input.substr(start, end - start);
}

std::string strip_comment(const std::string& input) {
    const size_t hash_pos = input.find('#');
    if (hash_pos == std::string::npos) {
        return trim_copy(input);
    }
    return trim_copy(input.substr(0, hash_pos));
}

std::vector<unsigned char> read_binary_file(const std::string& path) {
    std::ifstream stream(path, std::ios::binary | std::ios::ate);
    if (!stream) {
        throw std::runtime_error("Cannot open xclbin file: " + path);
    }
    std::streamsize size = stream.tellg();
    if (size <= 0) {
        throw std::runtime_error("xclbin file is empty: " + path);
    }
    stream.seekg(0, std::ios::beg);

    std::vector<unsigned char> data(static_cast<size_t>(size));
    if (!stream.read(reinterpret_cast<char*>(data.data()), size)) {
        throw std::runtime_error("Cannot read xclbin file: " + path);
    }
    return data;
}

std::vector<uint8_t> read_syndromes_file(const std::string& path) {
    std::ifstream stream(path);
    if (!stream) {
        throw std::runtime_error("Cannot open syndromes file: " + path);
    }

    std::vector<uint8_t> syndromes;
    std::string line;
    while (std::getline(stream, line)) {
        const std::string cleaned = strip_comment(line);
        if (cleaned.empty()) {
            continue;
        }
        std::istringstream iss(cleaned);
        int value = 0;
        if (!(iss >> value) || (iss >> std::ws && !iss.eof())) {
            throw std::runtime_error("Invalid syndrome line: " + line);
        }
        if (value < 0 || value > 63) {
            throw std::runtime_error("Syndrome must be in [0,63], got: " + std::to_string(value));
        }
        syndromes.push_back(static_cast<uint8_t>(value));
    }

    if (syndromes.empty()) {
        throw std::runtime_error("Syndromes file has no data: " + path);
    }

    return syndromes;
}

std::vector<uint8_t> read_lut_file(const std::string& path) {
    std::ifstream stream(path);
    if (!stream) {
        throw std::runtime_error("Cannot open LUT file: " + path);
    }

    std::vector<uint8_t> lut;
    std::string line;
    while (std::getline(stream, line)) {
        const std::string cleaned = strip_comment(line);
        if (cleaned.empty()) {
            continue;
        }
        unsigned int value = 0;
        std::stringstream ss(cleaned);
        ss >> std::hex >> value;
        if (!ss || (ss >> std::ws && !ss.eof()) || value > 0xFFU) {
            throw std::runtime_error("Invalid LUT byte (expect hex 00..FF): " + line);
        }
        lut.push_back(static_cast<uint8_t>(value));
    }

    if (lut.size() != 64) {
        throw std::runtime_error("LUT file must contain exactly 64 entries, found: " + std::to_string(lut.size()));
    }

    return lut;
}

struct ParsedInstruction {
    uint8_t op;
    uint8_t qubit;
    bool apply;
};

ParsedInstruction parse_instruction(uint8_t instr) {
    const uint8_t op = instr & 0x3;
    const uint8_t qubit = (instr >> 2) & 0x7;
    const uint8_t valid = (instr >> 5) & 0x1;
    const bool apply = (valid == 1) && (op >= 1 && op <= 3) && (qubit <= 6);
    return {op, qubit, apply};
}

uint8_t steane_column_bits(uint8_t qubit) {
    static constexpr std::array<uint8_t, 7> kColumns = {
        0x07,  // q0 -> 111
        0x03,  // q1 -> 110
        0x05,  // q2 -> 101
        0x06,  // q3 -> 011
        0x01,  // q4 -> 100
        0x02,  // q5 -> 010
        0x04,  // q6 -> 001
    };
    return kColumns[qubit];
}

uint8_t instruction_syndrome(uint8_t instr) {
    const ParsedInstruction parsed = parse_instruction(instr);
    if (!parsed.apply) {
        return 0;
    }

    const uint8_t col = steane_column_bits(parsed.qubit);
    if (parsed.op == 1) {
        return col;  // X -> X-syndrome only
    }
    if (parsed.op == 3) {
        return static_cast<uint8_t>(col << 3);  // Z -> Z-syndrome only
    }
    return static_cast<uint8_t>(col | (col << 3));  // Y -> both parts
}

struct CorrectionSummary {
    size_t total = 0;
    size_t no_correction = 0;
    size_t already_zero = 0;
    size_t corrections_applied = 0;
    size_t corrected_to_zero = 0;
    size_t residual_non_zero = 0;
    std::array<size_t, 4> op_counts = {0, 0, 0, 0};
    std::array<size_t, 7> qubit_counts = {0, 0, 0, 0, 0, 0, 0};
};

CorrectionSummary build_correction_summary(
    const std::vector<uint8_t>& syndromes,
    const std::vector<uint8_t>& instructions
) {
    if (syndromes.size() != instructions.size()) {
        throw std::runtime_error("Cannot summarize corrections: size mismatch.");
    }

    CorrectionSummary summary;
    summary.total = instructions.size();

    for (size_t i = 0; i < instructions.size(); ++i) {
        const uint8_t syn = static_cast<uint8_t>(syndromes[i] & 0x3F);
        const ParsedInstruction parsed = parse_instruction(instructions[i]);

        if (!parsed.apply) {
            ++summary.no_correction;
            if (syn == 0) {
                ++summary.already_zero;
            }
            continue;
        }

        ++summary.corrections_applied;
        ++summary.op_counts[parsed.op];
        ++summary.qubit_counts[parsed.qubit];

        const uint8_t residual = static_cast<uint8_t>(syn ^ instruction_syndrome(instructions[i]));
        if (residual == 0) {
            ++summary.corrected_to_zero;
        } else {
            ++summary.residual_non_zero;
        }
    }

    return summary;
}

void print_correction_summary(const CorrectionSummary& s) {
    auto pct = [&](size_t value) -> double {
        if (s.total == 0) {
            return 0.0;
        }
        return (100.0 * static_cast<double>(value)) / static_cast<double>(s.total);
    };

    std::cout << "\n=== Error-Correction Summary ===\n";
    std::cout << "Total syndromes: " << s.total << "\n";
    std::cout << "Corrections applied: " << s.corrections_applied
              << " (" << std::fixed << std::setprecision(2) << pct(s.corrections_applied) << "%)\n";
    std::cout << "No correction: " << s.no_correction
              << " (" << std::fixed << std::setprecision(2) << pct(s.no_correction) << "%)\n";
    std::cout << "No correction because syndrome already zero: " << s.already_zero << "\n";
    std::cout << "Applied correction -> residual syndrome 000000: " << s.corrected_to_zero << "\n";
    std::cout << "Applied correction -> residual syndrome non-zero: " << s.residual_non_zero << "\n";

    std::cout << "\nOperation counts:\n";
    std::cout << "X: " << s.op_counts[1] << "\n";
    std::cout << "Y: " << s.op_counts[2] << "\n";
    std::cout << "Z: " << s.op_counts[3] << "\n";

    std::cout << "\nQubit correction counts:\n";
    for (size_t q = 0; q < s.qubit_counts.size(); ++q) {
        std::cout << "q" << q << ": " << s.qubit_counts[q] << "\n";
    }
}

std::string decode_instruction(uint8_t instr) {
    const ParsedInstruction parsed = parse_instruction(instr);

    std::string op_name = "I";
    if (parsed.op == 1) op_name = "X";
    if (parsed.op == 2) op_name = "Y";
    if (parsed.op == 3) op_name = "Z";

    std::ostringstream out;
    if (!parsed.apply) {
        out << "No correction";
    } else {
        out << "Apply " << op_name << " on qubit " << static_cast<int>(parsed.qubit);
    }
    return out.str();
}

cl::Device get_xilinx_device() {
    std::vector<cl::Platform> platforms;
    cl::Platform::get(&platforms);
    for (const auto& platform : platforms) {
        std::string vendor = platform.getInfo<CL_PLATFORM_VENDOR>();
        if (vendor.find("Xilinx") == std::string::npos) {
            continue;
        }
        std::vector<cl::Device> devices;
        platform.getDevices(CL_DEVICE_TYPE_ACCELERATOR, &devices);
        if (!devices.empty()) {
            return devices[0];
        }
    }
    throw std::runtime_error("No Xilinx accelerator device found.");
}

}  // namespace

int main(int argc, char** argv) {
    if (argc != 4) {
        std::cerr << "Usage: " << argv[0] << " <xclbin> <syndromes.txt> <decoder_lut.hex>\n";
        return 1;
    }

    try {
        const std::string xclbin_path = argv[1];
        const std::string syndromes_path = argv[2];
        const std::string lut_path = argv[3];

        auto xclbin = read_binary_file(xclbin_path);
        auto syndromes = read_syndromes_file(syndromes_path);
        auto lut = read_lut_file(lut_path);
        
        // Pad the input syndromes to be a multiple of 64 bytes (512-bit bus width)
        size_t original_syndrome_count = syndromes.size();
        size_t padded_syndrome_count = ((original_syndrome_count + 63) / 64) * 64;
        syndromes.resize(padded_syndrome_count, 0);

        std::vector<uint8_t> instructions(padded_syndrome_count, 0);

        cl::Device device = get_xilinx_device();
        cl::Context context(device);
        cl::CommandQueue queue(context, device, CL_QUEUE_PROFILING_ENABLE);

        cl::Program::Binaries bins;
    #if defined(CL_HPP_ENABLE_PROGRAM_CONSTRUCTION_FROM_ARRAY_COMPATIBILITY)
        bins.push_back({xclbin.data(), xclbin.size()});
    #else
        bins.push_back(xclbin);
    #endif
        std::vector<cl_int> binary_status;
        cl::Program program(context, {device}, bins, &binary_status);
        if (binary_status.empty() || binary_status[0] != CL_SUCCESS) {
            throw std::runtime_error("Failed to load xclbin onto device.");
        }

        cl::Kernel kernel(program, "steane_decoder_kernel");

        cl::Buffer syndromes_buf(
            context,
            CL_MEM_READ_ONLY | CL_MEM_COPY_HOST_PTR,
            sizeof(uint8_t) * syndromes.size(),
            syndromes.data()
        );
        cl::Buffer lut_buf(
            context,
            CL_MEM_READ_ONLY | CL_MEM_COPY_HOST_PTR,
            sizeof(uint8_t) * lut.size(),
            lut.data()
        );
        cl::Buffer instructions_buf(
            context,
            CL_MEM_WRITE_ONLY,
            sizeof(uint8_t) * instructions.size()
        );

        kernel.setArg(0, syndromes_buf);
        kernel.setArg(1, lut_buf);
        kernel.setArg(2, instructions_buf);
        
        // Pass the number of 512-bit chunks (64 bytes each)
        kernel.setArg(3, static_cast<int>(padded_syndrome_count / 64));

        const auto host_start = std::chrono::steady_clock::now();
        cl::Event input_migrate_event;
        cl::Event output_read_event;
        cl::Event kernel_event;
        // Start transferring inputs
        queue.enqueueMigrateMemObjects({syndromes_buf, lut_buf}, 0, nullptr, &input_migrate_event);
        
        // Execute the kernel and track the event
        queue.enqueueTask(kernel, nullptr, &kernel_event);
        queue.finish();

        // Read results back
        queue.enqueueReadBuffer(
            instructions_buf,
            CL_TRUE,
            0,
            sizeof(uint8_t) * instructions.size(),
            instructions.data(),
            nullptr,
            &output_read_event
        );

        // Calculate timing using OpenCL profiling plus host wall-clock elapsed time.
        cl_ulong input_start = 0;
        cl_ulong input_end = 0;
        cl_ulong time_start = 0;
        cl_ulong time_end = 0;
        cl_ulong output_start = 0;
        cl_ulong output_end = 0;

        input_migrate_event.getProfilingInfo(CL_PROFILING_COMMAND_START, &input_start);
        input_migrate_event.getProfilingInfo(CL_PROFILING_COMMAND_END, &input_end);
        kernel_event.getProfilingInfo(CL_PROFILING_COMMAND_START, &time_start);
        kernel_event.getProfilingInfo(CL_PROFILING_COMMAND_END, &time_end);
        output_read_event.getProfilingInfo(CL_PROFILING_COMMAND_START, &output_start);
        output_read_event.getProfilingInfo(CL_PROFILING_COMMAND_END, &output_end);

        const double input_time_ns = static_cast<double>(input_end - input_start);
        const double kernel_time_ns = static_cast<double>(time_end - time_start);
        const double output_time_ns = static_cast<double>(output_end - output_start);
        const auto host_end = std::chrono::steady_clock::now();
        const auto host_time_ns = std::chrono::duration_cast<std::chrono::nanoseconds>(
            host_end - host_start
        ).count();

        std::cout << "\n================ TIMING PROFILING ================\n";
        std::cout << "Host-to-device transfer time:     " << input_time_ns << " ns\n";
        std::cout << "Kernel profiling start:          " << time_start << " ns\n";
        std::cout << "Kernel profiling end:            " << time_end << " ns\n";
        std::cout << "Total FPGA Kernel Execution Time: " << kernel_time_ns << " ns\n";
        std::cout << "Per-syndrome decoder time:       " << (kernel_time_ns / original_syndrome_count) << " ns\n";
        std::cout << "Device-to-host readback time:     " << output_time_ns << " ns\n";
        std::cout << "Host end-to-end elapsed time:     " << host_time_ns << " ns\n";
        std::cout << "==================================================\n\n";

        std::cout << "Decoded " << original_syndrome_count << " syndrome entries\n";
        for (size_t i = 0; i < original_syndrome_count; ++i) {
            std::cout
                << "syndrome=" << std::setw(2) << static_cast<int>(syndromes[i])
                << " instruction=0x"
                << std::hex << std::setw(2) << std::setfill('0') << static_cast<int>(instructions[i])
                << std::dec << std::setfill(' ')
                << " -> " << decode_instruction(instructions[i])
                << "\n";
        }

        // Generate summary based only on the original valid syndrome data (ignore padding zeros)
        syndromes.resize(original_syndrome_count);
        instructions.resize(original_syndrome_count);
        const CorrectionSummary summary = build_correction_summary(syndromes, instructions);
        print_correction_summary(summary);

        return 0;
    } catch (const std::exception& ex) {
        std::cerr << "Error: " << ex.what() << "\n";
        return 1;
    }
}
