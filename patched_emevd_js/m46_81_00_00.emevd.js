// ==EMEVD==
// @docs    nr-common.emedf.json
// @compress    None
// @game    Sekiro
// @string    "W:\\CL\\data\\Param\\event\\common_func.emevd\u0000W:\\CL\\data\\Param\\event\\common_macro.emevd\u0000\u0000\u0000\u0000\u0000\u0000"
// @linked    [0,82]
// @version    3.6.3
// ==/EMEVD==

$Event(0, Default, function() {
    $InitializeCommonEvent(0, 90015000, 0, 46810800, 902100600, 30, 0, 0);
    $InitializeCommonEvent(0, 99055500, 46810800, 15);
    $InitializeCommonEvent(0, 90015030, 0, 46810800, 30, 921510, 0);
    $InitializeCommonEvent(0, 90015002, 0, 0, 46810800, 46810800, 1020, 921510, 11290, 902100600, 46810800);
    $InitializeCommonEvent(0, 9005810, 46810800, 46810500, 46811500, 5);
    $InitializeCommonEvent(0, 90015005, 46811500, 46812800, 46810800);
    GotoIf(S0, Signed(0) != 0);
    GotoIf(S0, 0 != 0);
    Goto(S1);
S0:
    $InitializeCommonEvent(0, 90015008, 0, 46810800, 921510, 46810800, 0, 0);
S1:
    if (0 != 0) {
        $InitializeCommonEvent(0, 90015013);
    }
    $InitializeCommonEvent(0, 90015015, 46810800);
    $InitializeCommonEvent(0, 90015016, 46810800);
    if (EventFlag(7604)) {
        $InitializeCommonEvent(0, 90015071, 46810800);
        $InitializeCommonEvent(0, 90015468, 46810800, 8270, 8247);
    }
    $InitializeCommonEvent(0, 90015199, 46810800);
});

$Event(45512200, Default, function(chrEntityId) {
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
