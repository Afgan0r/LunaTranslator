#pragma once

#include <cstdint>
#include <cstring>
#include <optional>

namespace grisaia
{
  struct ModelRoles
  {
    unsigned body, name;
  };

  // The fingerprinted engine indexes models by a 32-byte alias and ordinal.
  // Resolve its active str[0]/name[0] aliases instead of presentation IDs.
  template <typename Read>
  std::optional<ModelRoles> modelRoles(uintptr_t registry, uintptr_t current, Read read)
  {
    auto word = [&](uintptr_t address) -> std::optional<uint32_t>
    {
      uint32_t value;
      if (!address || !read(address, &value, sizeof(value)))
        return {};
      return value;
    };
    auto tree = word(registry);
    if (!tree || !*tree)
      return {};
    auto head = word(*tree + 0x18);
    if (!head || !*head)
      return {};
    auto lookup = [&](const char *alias) -> std::optional<uint32_t>
    {
      auto node = word(*head + 4);
      for (unsigned depth = 0; depth < 64 && node && *node && *node != *head; ++depth)
      {
        char key[32];
        auto index = word(*node + 44);
        if (!index || !read(*node + 12, key, sizeof(key)) ||
            !memchr(key, 0, sizeof(key)))
          return {};
        const auto order = strcmp(alias, key);
        if (!order && !*index)
          return word(*node + 48);
        const bool right = order > 0 || (!order && static_cast<int32_t>(*index) < 0);
        node = word(*node + (right ? 8 : 0));
      }
      return {};
    };
    auto body = lookup("str"), name = lookup("name");
    if (!body || !name || !*body || !*name || *body != current || *body == *name ||
        word(*body + 4) != 20 || word(*name + 4) != 20)
      return {};
    auto owner = word(*body + 12);
    if (!owner || !*owner || word(*name + 12) != owner)
      return {};
    auto bodyId = word(*body + 0x3bc), nameId = word(*name + 0x3bc);
    if (!bodyId || !nameId || !*bodyId || !*nameId || bodyId == nameId)
      return {};
    return ModelRoles{*bodyId, *nameId};
  }
}
