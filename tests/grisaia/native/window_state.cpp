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
  state.observe(grisaia::bodyWindow, grisaia::clearText, 100);
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
  state.observe(grisaia::bodyWindow, grisaia::clearText, 100);
  state.observe(grisaia::bodyWindow, grisaia::appendText, 100);
  auto repeated = state.commit("session", "Same reply", "Speaker");
  require(bool(repeated) && *repeated != *first && state.serial == 2);
  state.observe(grisaia::bodyWindow, grisaia::clearText, 100);
  require(!state.commit("session", "", ""));
  state.observe(grisaia::bodyWindow, grisaia::appendText, 100);
  auto narration = state.commit("session", "Narration", "");
  require(bool(narration) && narration->find("\"speaker\":\"\"") != std::string::npos);
  state.observe(grisaia::bodyWindow, 0x1b7, 200);
  require(bool(state.commit("session", "Recreated window", "")));
  require(grisaia::jsonString("quote\"\\\n") == "\"quote\\\"\\\\\\u000a\"");
  std::cout << "Window generation, redraw suppression, real repeats, empty speaker, and JSON passed.\n";
}
