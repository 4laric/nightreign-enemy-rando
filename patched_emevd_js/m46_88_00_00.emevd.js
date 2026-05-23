// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 90015000, 0, 46880800, 904020540, 30, 0, 0);
    $InitializeCommonEvent(0, 99055500, 46880800, 15);
    $InitializeCommonEvent(0, 90015030, 0, 46880800, 30, 921210, 0);
    $InitializeCommonEvent(0, 90015002, 0, 0, 46880800, 46880800, 1020, 921210, 11290, 904020540, 46880800);
    $InitializeCommonEvent(0, 9005810, 46880800, 46880500, 46881500, 5);
    $InitializeCommonEvent(0, 90015005, 46881500, 46882800, 46880800);
    GotoIf(S0, Signed(0) != 0);
    GotoIf(S0, 0 != 0);
    Goto(S1);
S0:
    $InitializeCommonEvent(0, 90015008, 0, 46880800, 921210, 46880800, 0, 0);
S1:
    if (0 != 0) {
        $InitializeCommonEvent(0, 90015013);
    }
    $InitializeCommonEvent(0, 90015015, 46880800);
    $InitializeCommonEvent(0, 90015016, 46880800);
    if (EventFlag(7604)) {
        $InitializeCommonEvent(0, 90015071, 46880800);
        $InitializeCommonEvent(0, 90015468, 46880800, 8270, 8247);
    }
    $InitializeCommonEvent(0, 90015199, 46880800);
});

$Event(46592200, Default, function(chrEntityId) {
    EndIf(
        !(!EventFlag(7603)
            && (InArea(chrEntityId, 1045392989)
                || InArea(chrEntityId, 1045392988)
                || InArea(chrEntityId, 1044362996)
                || InArea(chrEntityId, 1045382998)
                || InArea(chrEntityId, 1045382997)
                || InArea(chrEntityId, 1045362996)
                || InArea(chrEntityId, 1045362995)
                || InArea(chrEntityId, 1045362994))));
    DisableCharacter(chrEntityId);
    DisableCharacterCollision(chrEntityId);
});
