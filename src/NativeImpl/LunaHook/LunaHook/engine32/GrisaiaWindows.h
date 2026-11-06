#pragma once

#include "GrisaiaWindowState.h"
#include <Wincrypt.h>
#pragma comment(lib, "advapi32.lib")

namespace grisaia
{
  inline bool readMemory(uintptr_t address, void *destination, size_t size)
  {
    SIZE_T copied = 0;
    return address && ReadProcessMemory(GetCurrentProcess(), (void *)address,
                                       destination, size, &copied) && copied == size;
  }

  inline std::optional<uint32_t> readWord(uintptr_t address)
  {
    uint32_t value;
    if (!readMemory(address, &value, sizeof(value)))
      return {};
    return value;
  }

  inline bool knownExecutable()
  {
    wchar_t path[MAX_PATH];
    if (!GetModuleFileNameW(nullptr, path, MAX_PATH) ||
        _wcsicmp(PathFindFileNameW(path), L"Grisaia.exe"))
      return false;
    HANDLE file = CreateFileW(path, GENERIC_READ, FILE_SHARE_READ, nullptr,
                              OPEN_EXISTING, FILE_FLAG_SEQUENTIAL_SCAN, nullptr);
    if (file == INVALID_HANDLE_VALUE)
      return false;
    HCRYPTPROV provider = 0;
    HCRYPTHASH hash = 0;
    bool ok = CryptAcquireContextW(&provider, nullptr, nullptr, PROV_RSA_AES,
                                   CRYPT_VERIFYCONTEXT) &&
              CryptCreateHash(provider, CALG_SHA_256, 0, 0, &hash);
    BYTE chunk[65536];
    DWORD count = 0;
    while (ok)
    {
      if (!ReadFile(file, chunk, sizeof(chunk), &count, nullptr))
      {
        ok = false;
        break;
      }
      if (!count)
        break;
      ok = CryptHashData(hash, chunk, count, 0);
    }
    constexpr BYTE expected[] = {
        0x99, 0x23, 0x00, 0x25, 0x75, 0xea, 0xce, 0x01, 0xf2, 0x2a, 0x1d, 0xcf, 0xc9, 0x34, 0x95, 0x97,
        0xb4, 0x09, 0x38, 0x9b, 0x17, 0x6f, 0x4d, 0x5d, 0xea, 0x79, 0xd8, 0x82, 0x6e, 0x74, 0x5b, 0x2f};
    BYTE actual[sizeof(expected)];
    count = sizeof(actual);
    ok = ok && CryptGetHashParam(hash, HP_HASHVAL, actual, &count, 0) &&
         count == sizeof(expected) && !memcmp(actual, expected, sizeof(expected));
    if (hash)
      CryptDestroyHash(hash);
    if (provider)
      CryptReleaseContext(provider, 0);
    CloseHandle(file);
    return ok;
  }

  // Read the completed glyph vector while still on the game's presentation
  // thread. A host-side read could already see the next window during Skip.
  inline std::optional<std::string> glyphText(uintptr_t parent, uintptr_t base)
  {
    if (readWord(parent) != base + 0x25dc94)
      return {};
    auto renderer = readWord(parent + 0x2ac);
    if (!renderer || !*renderer)
      return {};
    auto layout = readWord(*renderer + 8);
    if (!layout || !*layout)
      return {};
    // A newly assigned, nonempty name must not reuse the previous glyphs.
    // Cleared empty name buffers are valid even before another layout pass.
    if (readWord(*layout + 0x284) != 0 && readWord(*layout + 0x19c) != 0)
      return {};
    uint32_t bounds[2];
    if (!readMemory(*layout + 0xc, bounds, sizeof(bounds)) || bounds[1] < bounds[0] ||
        (bounds[1] - bounds[0]) % 0x50 || (bounds[1] - bounds[0]) / 0x50 > 16384)
      return {};
    std::vector<BYTE> records(bounds[1] - bounds[0]);
    if (!records.empty() && !readMemory(bounds[0], records.data(), records.size()))
      return {};
    std::string bytes;
    for (size_t offset = 0; offset < records.size(); offset += 0x50)
    {
      WORD c;
      memcpy(&c, records.data() + offset + 4, sizeof(c));
      // The engine's 0..9 / 0xffff control records include visual wrapping.
      if (c <= 9 || c == 0xffff)
        continue;
      if (c > 0xff)
        bytes += char(c >> 8);
      bytes += char(c & 0xff);
    }
    if (bytes.empty())
      return std::string();
    auto wide = StringToWideString(bytes, 932);
    if (!wide)
      return {};
    return WideStringToString(*wide, CP_UTF8);
  }

  inline bool attach()
  {
    if (!knownExecutable())
      return false;
    const auto base = (uintptr_t)GetModuleHandleW(nullptr);
    constexpr BYTE controlProlog[] = {0x8b, 0x44, 0x24, 0x08, 0x83, 0xec, 0x2c};
    constexpr BYTE renderProlog[] = {0x8b, 0x4e, 0x08, 0xe8, 0x46, 0x3f, 0x00, 0x00};
    constexpr BYTE separatorCall[] = {0xe8, 0x31, 0x0a, 0xfe, 0xff};
    if (memcmp((void *)(base + 0x42000), controlProlog, sizeof(controlProlog)) ||
        memcmp((void *)(base + 0x140b52), renderProlog, sizeof(renderProlog)) ||
        memcmp((void *)(base + 0xf55ba), separatorCall, sizeof(separatorCall)))
      return false;
    static WindowState state;
    static std::mutex mutex;
    static const auto session = []
    {
      FILETIME now;
      GetSystemTimeAsFileTime(&now);
      uint64_t ticks = (uint64_t(now.dwHighDateTime) << 32) | now.dwLowDateTime;
      return std::to_string(GetCurrentProcessId()) + ":" + std::to_string(ticks);
    }();

    // Live traces distinguish this scenario separator from ordinary buffer
    // replacement/append, which backlog restoration also executes.
    {
      HookParam script;
      script.address = base + 0xf55ba;
      script.type = USING_STRING | CODEC_UTF8 | FULL_STRING | NO_CONTEXT;
      script.text_fun = [](hook_context *context, HookParam *, TextBuffer *buffer, uintptr_t *)
      {
        auto id = readWord(context->ecx + 0x3bc);
        if (!id)
        {
          buffer->from("{\"schema\":1,\"kind\":\"error\",\"code\":\"text_model_unavailable\"}");
          return;
        }
        std::lock_guard<std::mutex> lock(mutex);
        state.observeScenarioBoundary(*id);
        buffer->from("{\"schema\":1,\"kind\":\"script\",\"window\":" + std::to_string(*id) +
                     ",\"script_revision\":" + std::to_string(state.scriptRevision) + "}");
      };
      if (!NewHook(script, "GrisaiaScript"))
        return false;
    }

    HookParam control;
    control.address = base + 0x42000;
    control.type = USING_STRING | CODEC_UTF8 | FULL_STRING | NO_CONTEXT;
    control.text_fun = [](hook_context *context, HookParam *, TextBuffer *buffer, uintptr_t *)
    {
      const auto base = (uintptr_t)GetModuleHandleW(nullptr);
      if (readWord(context->ecx) != base + 0x25dc94)
        return;
      auto id = readWord(context->ecx + 4);
      if (!id || (*id != bodyWindow && *id != nameWindow))
        return;
      const auto message = context->stack[2];
      std::lock_guard<std::mutex> lock(mutex);
      state.observe(*id, message, context->ecx);
      if (message == initialize || message == appendText || message == clearText ||
          message == 0x1b5 || message == 0x1b7 || message == 0x1be)
        buffer->from("{\"schema\":1,\"kind\":\"control\",\"window\":" + std::to_string(*id) +
                     ",\"message\":" + std::to_string(message) +
                     ",\"revision\":" + std::to_string(state.revision) + "}");
    };
    if (!NewHook(control, "GrisaiaControl"))
      return false;

    HookParam window;
    // Immediately after complete layout generation, before per-glyph drawing.
    window.address = base + 0x140b52;
    window.type = USING_STRING | CODEC_UTF8 | FULL_STRING | NO_CONTEXT;
    window.text_fun = [](hook_context *context, HookParam *, TextBuffer *buffer, uintptr_t *)
    {
      std::lock_guard<std::mutex> lock(mutex);
      if (!state.bodyParent || state.revision == state.sentRevision ||
          readWord(state.bodyParent + 0x2ac) != context->esi)
        return;
      const auto base = (uintptr_t)GetModuleHandleW(nullptr);
      auto text = glyphText(state.bodyParent, base);
      auto speaker = glyphText(state.nameParent, base);
      if (!text || !speaker)
      {
        buffer->from("{\"schema\":1,\"kind\":\"error\",\"code\":\"capture_unavailable\"}");
        return;
      }
      auto packet = state.commit(session, *text, *speaker);
      if (!packet)
        return;
      if (packet->size() > TEXT_BUFFER_SIZE)
        buffer->from("{\"schema\":1,\"kind\":\"error\",\"code\":\"capture_too_large\"}");
      else
        buffer->from(*packet);
    };
    return NewHook(window, "GrisaiaWindows");
  }
}
