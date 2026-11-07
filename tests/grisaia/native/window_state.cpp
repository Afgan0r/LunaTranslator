#include "GrisaiaWindowState.h"
#include "GrisaiaModelRoles.h"
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <vector>

void require(bool value)
{
  if (!value)
    throw std::runtime_error("Window-state regression");
}

int main()
{
  constexpr unsigned bodyWindow = 15, nameWindow = 16;
  grisaia::WindowState state;
  state.bindWindows(bodyWindow, nameWindow);
  require(!state.commit("session", "Initial", ""));
  state.observeScenarioBoundary(bodyWindow);
  state.observe(bodyWindow, grisaia::clearText, 100);
  state.observeScenarioBoundary(bodyWindow);
  state.observe(bodyWindow, grisaia::appendText, 100);
  auto first = state.commit("session", "Same reply", "Speaker");
  require(bool(first));
  require(!state.commit("session", "Same reply", "Speaker"));
  // Redraw, forced completion, and queries do not create a new occurrence.
  for (unsigned message : {0x1be, 0x1b5, 0x1b7, 0x1b4})
  {
    state.observe(bodyWindow, message, 100);
    require(!state.commit("session", "Same reply", "Speaker"));
  }
  // Backlog restoration clears/repopulates the presentation without running
  // scenario commands. Both returns keep the first occurrence's serial.
  for (unsigned restore = 0; restore < 2; ++restore)
  {
    state.observe(bodyWindow, grisaia::clearText, 100);
    state.observe(bodyWindow, grisaia::appendText, 100);
    auto snapshot = state.commit("session", "Same reply", "Speaker");
    require(bool(snapshot) && state.serial == 1);
    require(snapshot->find("\"serial\":1,") != std::string::npos);
  }
  // Name-only commands cannot turn a restored body into a new occurrence.
  state.observeScenarioBoundary(nameWindow);
  require(state.scriptRevision == 2);
  state.observeScenarioBoundary(bodyWindow);
  state.observe(bodyWindow, grisaia::clearText, 100);
  state.observeScenarioBoundary(bodyWindow);
  state.observe(bodyWindow, grisaia::appendText, 100);
  auto repeated = state.commit("session", "Same reply", "Speaker");
  require(bool(repeated) && *repeated != *first && state.serial == 2);
  state.observeScenarioBoundary(bodyWindow);
  state.observe(bodyWindow, grisaia::clearText, 100);
  require(!state.commit("session", "", ""));
  state.observeScenarioBoundary(bodyWindow);
  state.observe(bodyWindow, grisaia::appendText, 100);
  auto narration = state.commit("session", "Narration", "");
  require(bool(narration) && narration->find("\"speaker\":\"\"") != std::string::npos);
  auto serialBeforeRecreation = state.serial;
  state.observe(bodyWindow, 0x1b7, 200);
  require(bool(state.commit("session", "Recreated window", "")));
  require(state.serial == serialBeforeRecreation);
  // Recorded live pattern: a new window emits two scenario separators;
  // three presentation reconstructions emit none; the next window emits two.
  // Keep the text identical throughout to rule out content-based deduplication.
  grisaia::WindowState replay;
  replay.bindWindows(bodyWindow, nameWindow);
  const unsigned separators[] = {2, 0, 0, 0, 2, 2};
  const unsigned serials[] = {1, 1, 1, 1, 2, 3};
  for (size_t index = 0; index < 6; ++index)
  {
    for (unsigned marker = 0; marker < separators[index]; ++marker)
      replay.observeScenarioBoundary(bodyWindow);
    replay.observe(bodyWindow, grisaia::clearText, 100);
    replay.observe(bodyWindow, grisaia::appendText, 100);
    require(bool(replay.commit("replay", "Identical reply", "Speaker")));
    require(replay.serial == serials[index]);
  }
  require(grisaia::jsonString("quote\"\\\n") == "\"quote\\\"\\\\\\u000a\"");
  // A name may be initialized before the scenario selects its presentation.
  grisaia::WindowState routed;
  routed.observe(42, grisaia::clearText, 4200);
  routed.bindWindows(730, 42);
  routed.observeScenarioBoundary(730);
  routed.observe(730, grisaia::appendText, 7300);
  require(routed.nameParent == 4200);
  require(bool(routed.commit("route", "First scene", "Speaker")));
  routed.observeScenarioBoundary(15); // unrelated text cannot advance dialogue
  require(routed.scriptRevision == 1);
  routed.observe(102, grisaia::clearText, 10200);
  routed.bindWindows(101, 102);
  require(routed.bodyParent == 0 && routed.nameParent == 10200);
  routed.observeScenarioBoundary(101);
  routed.observe(101, grisaia::appendText, 10100);
  require(bool(routed.commit("route", "Second scene", "")) && routed.serial == 2);
  routed.observe(42, grisaia::appendText, 9999);
  require(routed.nameParent == 10200);
  routed.observe(101, grisaia::clearText, 10100);
  routed.observe(101, grisaia::appendText, 10100);
  require(bool(routed.commit("route", "Second scene", "")) && routed.serial == 2);

  // Synthetic engine registry: alias ordering, arbitrary IDs, shared owner.
  std::vector<unsigned char> memory(8192);
  auto put = [&](size_t address, uint32_t value)
  { std::memcpy(memory.data() + address, &value, sizeof(value)); };
  auto key = [&](size_t node, const char *alias, uint32_t model)
  {
    put(node, 200); put(node + 8, 200);
    std::memcpy(memory.data() + node + 12, alias, std::strlen(alias) + 1);
    put(node + 48, model);
  };
  put(100, 128); put(128 + 0x18, 200); put(204, 300);
  key(300, "name", 3000); key(400, "str", 1000); put(308, 400);
  put(1004, 20); put(3004, 20); put(1012, 700); put(3012, 700);
  put(1000 + 0x3bc, 730); put(3000 + 0x3bc, 42);
  size_t reads = 0;
  auto read = [&](uintptr_t address, void *output, size_t size)
  {
    ++reads;
    if (address >= memory.size() || size > memory.size() - address)
      return false;
    std::memcpy(output, memory.data() + address, size);
    return true;
  };
  auto roles = grisaia::modelRoles(100, 1000, read);
  require(bool(roles) && roles->body == 730 && roles->name == 42);
  require(!grisaia::modelRoles(100, 3000, read));
  put(3012, 701);
  require(!grisaia::modelRoles(100, 1000, read));
  put(3012, 700); put(3004, 4);
  require(!grisaia::modelRoles(100, 1000, read));
  put(3004, 20); put(3000 + 0x3bc, 730);
  require(!grisaia::modelRoles(100, 1000, read));
  put(3000 + 0x3bc, 42); put(308, 300); reads = 0;
  require(!grisaia::modelRoles(100, 1000, read) && reads < 300);
  require(!grisaia::modelRoles(9000, 1000, read));
  std::cout << "Script generation, backlog restoration, real repeats, empty speaker, and JSON passed.\n";
}
