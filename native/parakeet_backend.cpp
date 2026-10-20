// Expose the selected backend so Python can reject any silent CPU fallback.
#include "backend.hpp"
#include "ggml_graph.hpp"
extern "C" const char* hey_gpt_parakeet_backend() {
    try { pk::set_num_threads(2); return pk::global_backend().device_name(); }
    catch (...) { return "unavailable"; }
}
extern "C" void hey_gpt_parakeet_shutdown() { pk::shutdown_backend(); }
