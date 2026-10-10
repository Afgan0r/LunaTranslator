#pragma once

#include <cstdint>
#include <optional>
#include <string>

namespace grisaia
{
  // These are presentation messages, not script-reader or glyph callbacks.
  constexpr unsigned bodyWindow = 15, nameWindow = 16;
  constexpr unsigned initialize = 0x1b0, appendText = 0x1b2, clearText = 0x1b3;

  inline std::string jsonString(const std::string &text)
  {
    constexpr char digits[] = "0123456789abcdef";
    std::string result = "\"";
    for (unsigned char c : text)
    {
      if (c == '"' || c == '\\')
      {
        result += '\\';
        result += c;
      }
      else if (c < 0x20)
      {
        result += "\\u00";
        result += digits[c >> 4];
        result += digits[c & 15];
      }
      else
        result += c;
    }
    return result + '"';
  }

  struct WindowState
  {
    uintptr_t bodyParent = 0, nameParent = 0;
    uint64_t revision = 0, sentRevision = 0, serial = 0;

    void observe(unsigned id, unsigned message, uintptr_t parent)
    {
      if (id == nameWindow)
        nameParent = parent;
      if (id != bodyWindow)
        return;
      if (bodyParent != parent)
      {
        bodyParent = parent;
        ++revision;
      }
      if (message == initialize || message == appendText || message == clearText)
        ++revision;
    }

    std::optional<std::string> commit(const std::string &session,
                                     const std::string &text, const std::string &speaker)
    {
      if (text.empty() || !bodyParent || !revision || sentRevision == revision)
        return {};
      sentRevision = revision;
      ++serial;
      return "{\"schema\":1,\"kind\":\"window\",\"session\":" + jsonString(session) +
             ",\"serial\":" + std::to_string(serial) + ",\"text\":" + jsonString(text) +
             ",\"speaker\":" + jsonString(speaker) + "}";
    }
  };
}
