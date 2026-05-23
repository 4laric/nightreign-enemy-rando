// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 99055500, 1042390282, 15);
    $InitializeCommonEvent(0, 91005506, 1042395200);
    $InitializeCommonEvent(0, 90005580, 1042391950, 1042390950, 7652);
    $InitializeCommonEvent(0, 9005810, 1042390800, 1042390951, 1042391951, 5);
    $InitializeCommonEvent(0, 90015005, 1042391951, 1042390951, 1042390800);
    $InitializeCommonEvent(0, 90015000, 1042392901, 1042390851, 907550002, 30, 756020, 8110);
    $InitializeCommonEvent(0, 99055500, 1042390851, 15);
    $InitializeCommonEvent(0, 90015030, 1042392901, 1042390851, 30, 756020, 8110);
    $InitializeCommonEvent(0, 90015002, 0, 1042392901, 1042390850, 1042390851, 1020, 0, 0, 0, 0);
    $InitializeCommonEvent(0, 90015160, 1042390850, 1042392901);
    $InitializeCommonEvent(0, 90015161, 1042390850, 1042392900);
    $InitializeCommonEvent(0, 90015162, 1042390850, 1042392900, 1042392901);
    $InitializeCommonEvent(0, 90015163, 1042390851, 1042392900, 1042392901, 1042390850);
    $InitializeCommonEvent(0, 90015164, 1042390850, 1042392901);
    $InitializeCommonEvent(0, 90065901, 1042394890);
    $InitializeCommonEvent(0, 90005910, 1042391800, 7677);
    $InitializeCommonEvent(0, 91005505, 1042392510, 7677);
    $InitializeCommonEvent(0, 90015150, 1042390200, 73059);
    $InitializeCommonEvent(0, 90015151, 1042390200, 74019);
    $InitializeCommonEvent(0, 90015152, 1042390200, 74019);
    $InitializeCommonEvent(0, 90015140, 1042391200, 200, 9100, 1042398200);
    $InitializeCommonEvent(0, 90015501, 1042392300, 73991);
});

$Event(1042392920, Restart, function() {
    WaitFor(MissionActive(403));
    EndIf(EventFlag(1042392930));
    SetSpEffect(1042390280, 99840);
    WaitFor(ActionButtonInArea(4351, 1042390280));
    ClearSpEffect(1042390280, 99840);
    SetCharacterBackreadState(1042395900, false);
});

$Event(1042392930, Restart, function() {
    WaitFor(MissionActive(403) && EventFlag(1042392920));
    WaitFor(CharacterDead(1042390281) && CharacterDead(1042390282));
    SetEventFlagID(8410, ON);
});

$Event(1042392940, Restart, function() {
    WaitFor(MissionActive(202));
    EndIf(EventFlag(1042392950));
    SetCharacterBackreadState(1042390290, false);
});

$Event(1042392950, Restart, function() {
    WaitFor(MissionActive(202) && EventFlag(1042392940));
    WaitFor(CharacterDead(1042390290));
    SetEventFlagID(8355, ON);
});
