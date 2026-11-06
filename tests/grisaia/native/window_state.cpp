#include "GrisaiaWindowState.h"
#include <iostream>
#include <stdexcept>

void require(bool value)
{
  if (!value)
    throw std::runtime_error("Window-state regression");
}

int main()
{
  grisaia::WindowState state;
  require(!state.commit("session", "Initial", ""));
  state.observeScenarioBoundary(grisaia::bodyWindow);
  state.observe(grisaia::bodyWindow, grisaia::clearText, 100);
  state.observeScenarioBoundary(grisaia::bodyWindow);
  state.observe(grisaia::bodyWindow, grisaia::appendText, 100);
  auto first = state.commit("session", "Same reply", "Speaker");
  require(bool(first));
  require(!state.commit("session", "Same reply", "Speaker"));
  // Redraw, forced completion, and queries do not create a new occurrence.
  for (unsigned message : {0x1be, 0x1b5, 0x1b7, 0x1b4})
  {
    state.observe(grisaia::bodyWindow, message, 100);
    require(!state.commit("session", "Same reply", "Speaker"));
  }
  // Backlog restoration clears/repopulates the presentation without running
  // scenario commands. Both returns keep the first occurrence's serial.
  for (unsigned restore = 0; restore < 2; ++restore)
  {
    state.observe(grisaia::bodyWindow, grisaia::clearText, 100);
    state.observe(grisaia::bodyWindow, grisaia::appendText, 100);
    auto snapshot = state.commit("session", "Same reply", "Speaker");
    require(bool(snapshot) && state.serial == 1);
    require(snapshot->find("\"serial\":1,") != std::string::npos);
  }
  // Name-only commands cannot turn a restored body into a new occurrence.
  state.observeScenarioBoundary(grisaia::nameWindow);
  require(state.scriptRevision == 2);
  state.observeScenarioBoundary(grisaia::bodyWindow);
  state.observe(grisaia::bodyWindow, grisaia::clearText, 100);
  state.observeScenarioBoundary(grisaia::bodyWindow);
  state.observe(grisaia::bodyWindow, grisaia::appendText, 100);
  auto repeated = state.commit("session", "Same reply", "Speaker");
  require(bool(repeated) && *repeated != *first && state.serial == 2);
  state.observeScenarioBoundary(grisaia::bodyWindow);
  state.observe(grisaia::bodyWindow, grisaia::clearText, 100);
  require(!state.commit("session", "", ""));
  state.observeScenarioBoundary(grisaia::bodyWindow);
  state.observe(grisaia::bodyWindow, grisaia::appendText, 100);
  auto narration = state.commit("session", "Narration", "");
  require(bool(narration) && narration->find("\"speaker\":\"\"") != std::string::npos);
  auto serialBeforeRecreation = state.serial;
  state.observe(grisaia::bodyWindow, 0x1b7, 200);
  require(bool(state.commit("session", "Recreated window", "")));
  require(state.serial == serialBeforeRecreation);
  // Recorded live pattern: a new window emits two scenario separators;
  // three presentation reconstructions emit none; the next window emits two.
  // Keep the text identical throughout to rule out content-based deduplication.
  grisaia::WindowState replay;
  const unsigned separators[] = {2, 0, 0, 0, 2, 2};
  const unsigned serials[] = {1, 1, 1, 1, 2, 3};
  for (size_t index = 0; index < 6; ++index)
  {
    for (unsigned marker = 0; marker < separators[index]; ++marker)
      replay.observeScenarioBoundary(grisaia::bodyWindow);
    replay.observe(grisaia::bodyWindow, grisaia::clearText, 100);
    replay.observe(grisaia::bodyWindow, grisaia::appendText, 100);
    require(bool(replay.commit("replay", "Identical reply", "Speaker")));
    require(replay.serial == serials[index]);
  }
  require(grisaia::jsonString("quote\"\\\n") == "\"quote\\\"\\\\\\u000a\"");
  std::cout << "Script generation, backlog restoration, real repeats, empty speaker, and JSON passed.\n";
}
