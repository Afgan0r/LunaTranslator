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
  state.observeScript(grisaia::bodyWindow, grisaia::clearText);
  state.observe(grisaia::bodyWindow, grisaia::clearText, 100);
  state.observeScript(grisaia::bodyWindow, grisaia::appendText);
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
  state.observeScript(grisaia::nameWindow, grisaia::appendText);
  require(state.scriptRevision == 2);
  state.observeScript(grisaia::bodyWindow, grisaia::clearText);
  state.observe(grisaia::bodyWindow, grisaia::clearText, 100);
  state.observeScript(grisaia::bodyWindow, grisaia::appendText);
  state.observe(grisaia::bodyWindow, grisaia::appendText, 100);
  auto repeated = state.commit("session", "Same reply", "Speaker");
  require(bool(repeated) && *repeated != *first && state.serial == 2);
  state.observeScript(grisaia::bodyWindow, grisaia::clearText);
  state.observe(grisaia::bodyWindow, grisaia::clearText, 100);
  require(!state.commit("session", "", ""));
  state.observeScript(grisaia::bodyWindow, grisaia::appendText);
  state.observe(grisaia::bodyWindow, grisaia::appendText, 100);
  auto narration = state.commit("session", "Narration", "");
  require(bool(narration) && narration->find("\"speaker\":\"\"") != std::string::npos);
  auto serialBeforeRecreation = state.serial;
  state.observe(grisaia::bodyWindow, 0x1b7, 200);
  require(bool(state.commit("session", "Recreated window", "")));
  require(state.serial == serialBeforeRecreation);
  require(grisaia::jsonString("quote\"\\\n") == "\"quote\\\"\\\\\\u000a\"");
  std::cout << "Script generation, backlog restoration, real repeats, empty speaker, and JSON passed.\n";
}
