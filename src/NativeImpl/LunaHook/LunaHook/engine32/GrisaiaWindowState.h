#pragma once

#include <array>
#include <cstdint>
#include <optional>
#include <string>
#include <utility>

namespace grisaia
{
  // Presentation mutations can also rebuild a window after closing backlog.
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
    unsigned bodyWindow = 0, nameWindow = 0;
    uintptr_t bodyParent = 0, nameParent = 0;
    uint64_t revision = 0, sentRevision = 0, serial = 0;
    uint64_t scriptRevision = 0, sentScriptRevision = 0;

    // A role can be resolved after its first presentation message. Retain only
    // recent parent identities, never text, until the engine supplies the route.
    std::array<std::pair<unsigned, uintptr_t>, 64> parents{};
    size_t nextParent = 0;

    void bindWindows(unsigned body, unsigned name)
    {
      if (bodyWindow == body && nameWindow == name)
        return;
      bodyWindow = body;
      nameWindow = name;
      bodyParent = nameParent = 0;
      for (const auto &entry : parents)
      {
        if (entry.first == body)
          bodyParent = entry.second;
        if (entry.first == name)
          nameParent = entry.second;
      }
      ++revision;
    }

    void observeScenarioBoundary(unsigned id)
    {
      if (id == bodyWindow)
        ++scriptRevision;
    }

    void observe(unsigned id, unsigned message, uintptr_t parent)
    {
      auto found = false;
      for (auto &entry : parents)
        if (entry.first == id)
        {
          entry.second = parent;
          found = true;
          break;
        }
      if (!found)
      {
        parents[nextParent] = {id, parent};
        nextParent = (nextParent + 1) % parents.size();
      }
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
      // Reconstructing the same presentation does not execute script commands.
      // Keep its identity, but emit the snapshot so a manually marked new run
      // can capture a loaded save even when its text is unchanged.
      if (!serial || scriptRevision != sentScriptRevision)
        ++serial;
      sentScriptRevision = scriptRevision;
      return "{\"schema\":1,\"kind\":\"window\",\"session\":" + jsonString(session) +
             ",\"serial\":" + std::to_string(serial) +
             ",\"render_revision\":" + std::to_string(revision) +
             ",\"script_revision\":" + std::to_string(scriptRevision) +
             ",\"text\":" + jsonString(text) +
             ",\"speaker\":" + jsonString(speaker) + "}";
    }
  };
}
